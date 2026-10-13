"""Self-hosted guardrails for the store customer service LiteLLM gateway.

The guardrails/ package is mounted into the litellm container by
docker-compose.yaml and registered in litellm_config.yaml:

- CustomerServiceInputGuardrail  (mode: pre_call)  masks PII in prompts and
  rejects clear prompt-injection attempts with HTTP 400.
- CustomerServiceOutputGuardrail (mode: post_call) masks PII and echoed
  credentials in completions, and blocks configured banned terms.

All checks are regex based and dependency free, so the gateway does not rely
on an external guardrail SaaS. Internal guardrail errors fail open (logged and
skipped) to keep the gateway serving; deliberate rejections raise
fastapi.HTTPException, which the LiteLLM proxy surfaces to the caller as 400.

Behaviour is toggled with environment variables (delivered via the litellm
service env_file in docker-compose.yaml):

- GUARDRAIL_MASK_PII=true                mask PII on input and output
- GUARDRAIL_BLOCK_PROMPT_INJECTION=true  reject prompt-injection patterns
- GUARDRAIL_BLOCKED_TERMS=a,b            block completions containing a/b
"""

import os
import re
from typing import Any, Dict, List, Optional, Pattern, Union

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- PII patterns --------------------------------------------------------------
# Hong Kong retail context: emails, card numbers, HKID and local (+852 /
# 8-digit) phone numbers. Plain integers (prices, quantities, order ids) are
# deliberately not matched: a bare 8-digit number is only treated as a phone
# when it starts with a HK mobile prefix (5/6/7/9); otherwise a separator
# ("9123 4567") or a +852 prefix is required.
PII_PATTERNS: List[tuple] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2})[ -]?\d{4}[ -]?\d{4}[ -]?\d{3,4}\b")),
    # No trailing \b: ")" and the following punctuation are both non-word
    # characters, so a boundary there never exists.
    ("HKID", re.compile(r"\b[A-Z]{1,2}\d{6}\(\d\)")),
    ("PHONE", re.compile(r"\+?852[\s-]?[2-9]\d{3}[\s-]?\d{4}|\b[2-9]\d{3}[\s-]\d{4}\b|\b[5679]\d{7}\b|\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{4}\b")),
]

# Environment variable names whose values must never appear in a completion.
SECRET_ENV_VARS = [
    "LITELLM_MASTER_KEY",
    "ZAI_API_KEY",
    "VLLM_API_KEY",
    "LANGFUSE_SECRET_KEY",
    "REDIS_SECRET_KEY",
    "MYSQL_PASSWORD",
    "POSTGRES_PASSWORD",
    "SENDER_PASSWORD",
]

# --- Prompt injection heuristics ----------------------------------------------
# Kept conservative: every pattern mentions instructions/prompts explicitly so
# ordinary customer sentences like "I want to ignore my previous order" do not
# trip them.
INJECTION_PATTERNS: List[Pattern] = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"ignore\s+(?:all|any|every|the)?\s*(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?|directions?)",
        r"disregard\s+(?:the\s+)?(?:above|previous|prior|earlier)",
        r"(?:reveal|show|print|repeat|output)\s+(?:your|the)\s+(?:system\s*prompt|initial\s+instructions?|hidden\s+instructions?|developer\s+instructions?)",
        r"you\s+are\s+now\s+(?:a|an)\s+",
        r"(?:enter|enable|activate)\s+(?:developer|dan|jailbreak)\s+mode",
        r"pretend\s+to\s+be\s+(?:a\s+different|an?\s+unrestricted|an?\s+uncensored)",
        r"override\s+(?:your\s+)?(?:instructions?|rules?|restrictions?|safety)",
    ]
]


def _mask_pii(text: str) -> str:
    for label, pattern in PII_PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text


def _mask_secrets(text: str) -> str:
    for name in SECRET_ENV_VARS:
        value = os.getenv(name, "")
        if value and len(value) >= 8 and value in text:
            text = text.replace(value, f"[REDACTED:{name}]")
    return text


def _find_injection(text: str) -> Optional[Pattern]:
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return pattern
    return None


def _transform_content(content: Any, transform) -> Any:
    """Apply transform to message content, which may be a string or an
    OpenAI-style list of content blocks ([{"type": "text", "text": ...}])."""

    if isinstance(content, str):
        return transform(content)
    if isinstance(content, list):
        transformed = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                transformed.append({**part, "text": transform(part["text"])})
            else:
                transformed.append(part)
        return transformed
    return content


def _message_text(message: Dict) -> str:
    """Flatten message content to plain text for scanning."""

    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _from_details(user_call_details: Any, key: str, default: Any = None) -> Any:
    """Read a field from the call details, which may be a plain dict (older
    LiteLLM) or a UserCallDetails object (newer LiteLLM)."""

    try:
        return user_call_details.get(key, default)
    except AttributeError:
        return getattr(user_call_details, key, default)


class CustomerServiceInputGuardrail(CustomGuardrail):
    """pre_call hook: mask PII in prompts, block prompt injection."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def async_pre_call_hook(self, user_call_details, call_type, **kwargs):
        try:
            return self._guard_request(user_call_details)
        except HTTPException:
            raise
        except Exception as e:
            # Fail open on internal errors so a guardrail bug cannot take the
            # whole gateway down; deliberate blocks re-raise above.
            print(f"[guardrail] input hook internal error (failing open): {e}", flush=True)
            return None

    def _guard_request(self, user_call_details) -> Any:
        messages = _from_details(user_call_details, "messages") or []

        mask_pii = _env_bool("GUARDRAIL_MASK_PII", True)
        block_injection = _env_bool("GUARDRAIL_BLOCK_PROMPT_INJECTION", True)

        guarded_messages = []
        for message in messages:
            if not isinstance(message, dict):
                guarded_messages.append(message)
                continue

            text = _message_text(message)

            if block_injection:
                pattern = _find_injection(text)
                if pattern:
                    detail = ("Blocked by customer-service-input-guard: "
                              f"prompt injection pattern matched ({pattern.pattern})")
                    print(f"[guardrail] {detail}", flush=True)
                    raise HTTPException(status_code=400, detail=detail)

            if mask_pii:
                guarded_messages.append(
                    {**message, "content": _transform_content(message.get("content"), _mask_pii)}
                )
            else:
                guarded_messages.append(message)

        try:
            user_call_details["messages"] = guarded_messages
        except TypeError:
            # Object-style call details: the returned mapping still carries
            # the guarded messages for LiteLLM to pick up.
            pass

        return user_call_details


class CustomerServiceOutputGuardrail(CustomGuardrail):
    """post_call hook: mask PII and credentials in completions, block banned
    terms."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def async_post_call_success_hook(self, data, user_call_details, **kwargs):
        try:
            return self._guard_response(data)
        except HTTPException:
            raise
        except Exception as e:
            print(f"[guardrail] output hook internal error (failing open): {e}", flush=True)
            return data

    def _guard_response(self, data) -> Any:
        if not isinstance(data, dict):
            return data

        blocked_terms = [term.strip()
                         for term in os.getenv("GUARDRAIL_BLOCKED_TERMS", "").split(",")
                         if term.strip()]
        mask_pii = _env_bool("GUARDRAIL_MASK_PII", True)

        for choice in data.get("choices") or []:
            if not isinstance(choice, dict):
                continue

            # Regular completions carry {"message": {...}}; streamed chunks
            # carry {"delta": {...}}.
            payload = choice.get("message") or choice.get("delta")
            if not isinstance(payload, dict):
                continue

            content = payload.get("content")
            if content is None:
                continue

            text = content if isinstance(content, str) else _message_text({"content": content})
            for term in blocked_terms:
                if term.lower() in text.lower():
                    detail = (f"Blocked by customer-service-output-guard: "
                              f"banned term matched ({term})")
                    print(f"[guardrail] {detail}", flush=True)
                    raise HTTPException(status_code=400, detail=detail)

            if mask_pii:
                payload["content"] = _transform_content(
                    content, lambda t: _mask_secrets(_mask_pii(t))
                )

        return data
