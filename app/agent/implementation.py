import os
import json
import uuid

from ag_ui.core import (
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
)
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.types import Command

from app.agent.agent import tracing
from app.agent.agent import coordinator
from app.agent.tools.render_tools import RENDER_TOOL_NAMES
from app.utils.response_checker import check_approval_wording

langfuse_callback_handler = tracing.langfuse_callback_handler
postgres_database_url = os.environ["POSTGRES_DATABASE_URL"]

# LangGraph node names in which the ROOT (coordinator) agent calls its model.
# deepagents builds the root graph with langchain's create_agent, whose model
# node is "model" (older prebuilts used "agent"); subagent runs execute inside
# the tools/task node and carry a non-empty langgraph_checkpoint_ns.
ROOT_MODEL_NODES = {"model", "agent"}


def _is_root_model_call(event: dict) -> bool:
    """True when a model event belongs to the root coordinator, not a subagent."""
    metadata = event.get("metadata") or {}
    node = metadata.get("langgraph_node")
    checkpoint_ns = metadata.get("langgraph_checkpoint_ns") or ""
    if checkpoint_ns:
        return False
    return node is None or node == "" or node in ROOT_MODEL_NODES


def _delta_text(chunk) -> str:
    """Extract the plain-text delta from an AIMessageChunk content field."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content
                 if isinstance(item, dict) and item.get("type") == "text"]
        return "".join(parts)
    return ""


def _final_text(output) -> str:
    """Extract the complete text from an on_chat_model_end output message."""
    if output is None:
        return ""
    content = getattr(output, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content
                 if isinstance(item, dict) and item.get("type") == "text"]
        return "".join(parts)
    return ""


# The event bus validates Response.response at max_length=10000; one oversized
# event would fail validation in the worker and silently kill the rest of the
# stream. Keep every serialised event comfortably below the cap by splitting
# long payloads — AG-UI clients concatenate TEXT_MESSAGE_CONTENT and
# TOOL_CALL_ARGS deltas before using them, so splitting is protocol-safe.
MAX_EVENT_DELTA_CHARS = 8000


def _text_content_events(message_id: str, text: str):
    """Yield TextMessageContentEvent(s) for text, split to respect the bus cap."""
    for start in range(0, len(text), MAX_EVENT_DELTA_CHARS):
        yield TextMessageContentEvent(message_id=message_id,
                                      delta=text[start:start + MAX_EVENT_DELTA_CHARS])


def _tool_args_events(tool_call_id: str, args_json: str):
    """Yield ToolCallArgsEvent(s) for args_json, split to respect the bus cap."""
    for start in range(0, len(args_json), MAX_EVENT_DELTA_CHARS):
        yield ToolCallArgsEvent(tool_call_id=tool_call_id,
                                delta=args_json[start:start + MAX_EVENT_DELTA_CHARS])


async def _translate_events(event_stream, thread_id: str, run_id: str):
    """Convert LangGraph astream_events (v2) into an AG-UI event stream.

    Each yielded value is an AG-UI protocol event (pydantic model); the caller
    (request worker) serialises each one into its own Response for the SSE
    pipeline.
    """
    # event run_id -> AG-UI message_id for the assistant message currently
    # being streamed from that model call.
    open_messages: dict = {}
    # event run_id -> tool_call_id for render tools currently executing.
    open_tool_calls: dict = {}
    # Fallback: last completed model output, used only when nothing was
    # streamed to the UI (e.g. a non-streaming model emits no stream events).
    fallback_text = ""
    emitted_any_text = False

    async for event in event_stream:
        event_name = event.get("event")
        event_run_id = event.get("run_id")
        data = event.get("data", {}) or {}

        if event_name == "on_chat_model_start":
            if _is_root_model_call(event):
                message_id = str(uuid.uuid4())
                open_messages[event_run_id] = message_id
                yield TextMessageStartEvent(message_id=message_id, role="assistant")

        elif event_name == "on_chat_model_stream":
            if not _is_root_model_call(event):
                continue
            message_id = open_messages.get(event_run_id)
            if message_id is None:
                continue
            delta = _delta_text(data.get("chunk"))
            if delta:
                emitted_any_text = True
                for content_event in _text_content_events(message_id, delta):
                    yield content_event

        elif event_name == "on_chat_model_end":
            if not _is_root_model_call(event):
                continue
            message_id = open_messages.pop(event_run_id, None)
            fallback_text = _final_text(data.get("output")) or fallback_text
            if message_id is not None:
                yield TextMessageEndEvent(message_id=message_id)

        elif event_name == "on_tool_start":
            tool_name = event.get("name")
            if tool_name in RENDER_TOOL_NAMES:
                tool_call_id = str(uuid.uuid4())
                open_tool_calls[event_run_id] = tool_call_id
                yield ToolCallStartEvent(
                    tool_call_id=tool_call_id,
                    tool_call_name=tool_name,
                    parent_message_id=str(uuid.uuid4()),
                )
                args_json = json.dumps(data.get("input") or {}, ensure_ascii=False)
                for args_event in _tool_args_events(tool_call_id, args_json):
                    yield args_event

        elif event_name == "on_tool_end":
            tool_call_id = open_tool_calls.pop(event_run_id, None)
            if tool_call_id is not None:
                yield ToolCallEndEvent(tool_call_id=tool_call_id)

        elif event_name == "on_chain_stream":
            chunk = data.get("chunk")
            if isinstance(chunk, dict):
                interrupt_info = chunk.get("__interrupt__")

                if isinstance(interrupt_info, tuple) and interrupt_info:
                    interrupt_info = interrupt_info[0]

                if hasattr(interrupt_info, "value"):
                    interrupt_info = interrupt_info.value

                if isinstance(interrupt_info, dict):
                    action_obj = interrupt_info.get("action_requests", {})

                    if isinstance(action_obj, list) and action_obj:
                        info = action_obj[0]
                        interrupt_description = (info.get("description", "")
                                                 or info.get("args", {}).get("description", ""))
                        if interrupt_description:
                            # Surface the human-approval interrupt as a normal
                            # assistant message so the customer can reply
                            # "agree"/"disagree" on the next turn.
                            message_id = str(uuid.uuid4())
                            yield TextMessageStartEvent(message_id=message_id, role="assistant")
                            for content_event in _text_content_events(message_id, interrupt_description):
                                yield content_event
                            yield TextMessageEndEvent(message_id=message_id)

    if not emitted_any_text and fallback_text:
        message_id = str(uuid.uuid4())
        yield TextMessageStartEvent(message_id=message_id, role="assistant")
        for content_event in _text_content_events(message_id, fallback_text):
            yield content_event
        yield TextMessageEndEvent(message_id=message_id)


async def agent_implementation(user_id, thread_id, request, id):
    """Run the coordinator agent and yield an AG-UI protocol event stream."""
    run_id = str(uuid.uuid4())
    try:
        print(f"Request of {user_id} (thread {thread_id}) submitted and handling by agent", flush=True)

        config = {
            "run_name": f"sql_agent_server_{id}",
            "callbacks": [langfuse_callback_handler],
            "configurable": {
                # thread_id keeps checkpointer conversation continuity across
                # HTTP requests; user_id pins the customer identity.
                "thread_id": f"{thread_id}",
                "user_id": f"{user_id}",
                "context": {"user_id": f"{user_id}"},
                "request_id": f"{id}"
            }
        }

        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)

        async with AsyncPostgresStore.from_conn_string(postgres_database_url) as store:
            await store.setup()

            coordinator_agent = await coordinator.build_coordinator_agent(user_id, store)
            print(f"The agent handling the request of {user_id} is built ", flush=True)

            approval_wording = check_approval_wording(request)

            if approval_wording:
                print(f"The agent service detected the approval wording:{approval_wording}")
                event_stream = coordinator_agent.astream_events(
                    Command(resume={"decisions": [{"type": f"{approval_wording}"}]}),
                    config=config,
                    version="v2"
                )
            else:
                event_stream = coordinator_agent.astream_events(
                    {"messages": [{"role": "user", "content": f"{request}"}]},
                    config=config,
                    version="v2"
                )

            async for agui_event in _translate_events(event_stream, thread_id, run_id):
                yield agui_event

        yield RunFinishedEvent(thread_id=thread_id, run_id=run_id)

    except Exception as e:
        print(f"[Agent]------agent_implementation raised:{str(e)}", flush=True)
        yield RunErrorEvent(message=str(e))
