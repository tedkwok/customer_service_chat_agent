"""Own FastAPI OAuth2 authorization server (authorization-code flow) + JWT.

Flow (public SPA client, no client secret, no PKCE — same trust level as the
legacy implicit flow but codes are single-use and short-lived):

    1. GET  /oauth/authorize?response_type=code&client_id=...&redirect_uri=...&state=...
       -> HTML login form
    2. POST /oauth/authorize (form fields incl. username/password)
       -> 302 redirect_uri?code=<single-use, 5 min>&state=...
    3. POST /oauth/token (grant_type=authorization_code)
       -> {access_token (JWT HS256), refresh_token, token_type, expires_in}

The web process runs single-instance (workers are multiprocessing children),
so authorization codes live in an in-process store with expiry + single-use
semantics.
"""

import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.BaseModel.customer_info import Customer_info
from app.BaseModel.user_credentials import User_Credentials
from app.connection.mysql import sql_engine

router = APIRouter()

JWT_SECRET = os.getenv("OAUTH_JWT_SECRET", "dev-only-insecure-secret")
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(minutes=int(os.getenv("OAUTH_TOKEN_TTL_MINUTES", "60")))
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "frontend")
REDIRECT_URIS = [u.strip() for u in os.getenv(
    "OAUTH_REDIRECT_URI", "http://localhost:5173/callback").split(",") if u.strip()]

AUTH_CODE_TTL_SECONDS = 300
PBKDF2_ITERATIONS = 200_000

# code -> {"customer_id", "username", "expires_at"}
_auth_codes: dict = {}


# --------------------------------------------------------------------------- #
# Password hashing (stdlib pbkdf2, constant-time verification)
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                    salt.encode("utf-8"), PBKDF2_ITERATIONS).hex()
    return hmac.compare_digest(candidate, digest)


# --------------------------------------------------------------------------- #
# JWT helpers
# --------------------------------------------------------------------------- #

def _create_token(customer_id: str, username: str, token_type: str,
                  expires_delta: timedelta) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": customer_id,
        "username": username,
        "typ": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    if payload.get("typ") != expected_type:
        raise HTTPException(status_code=401, detail=f"Expected a {expected_type} token")
    return payload


def get_current_user_payload(request: Request) -> dict:
    """FastAPI dependency: require a valid Bearer access token."""
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing Bearer access token")
    return _decode_token(token, "access")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


@router.post("/api/auth/register", status_code=201)
def register(body: RegisterRequest):
    with Session(sql_engine) as session:
        existing = session.scalar(select(User_Credentials)
                                  .where(User_Credentials.username == body.username))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already registered")

        customer_id = f"cu_{uuid.uuid4().hex[:8]}"

        # Every login credential maps to one customer_info row; both are
        # created together so the agent tools and the top-up page can operate
        # on the new account immediately.
        session.add(Customer_info(customer_id=customer_id))
        session.add(User_Credentials(username=body.username,
                                     password_hash=hash_password(body.password),
                                     customer_id=customer_id))
        session.commit()

    return {"customer_id": customer_id, "username": body.username,
            "message": "Account created. You can now log in."}


# --------------------------------------------------------------------------- #
# Authorization-code flow
# --------------------------------------------------------------------------- #

def _validate_client(client_id: str, redirect_uri: str, response_type: str):
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type: only 'code' is supported")
    if client_id != CLIENT_ID:
        raise HTTPException(status_code=400, detail="invalid_client_id")
    if redirect_uri not in REDIRECT_URIS:
        raise HTTPException(status_code=400, detail="invalid_redirect_uri")


_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>store_customer_service — Sign in</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #f5f6fa; }}
 .card {{ max-width: 360px; margin: 12vh auto; background: #fff; padding: 2rem;
          border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
 h1 {{ font-size: 1.2rem; }} label {{ display: block; margin-top: 1rem; font-size: .9rem; }}
 input[type=text], input[type=password] {{ width: 100%; padding: .5rem; margin-top: .25rem;
          border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }}
 button {{ margin-top: 1.5rem; width: 100%; padding: .6rem; border: 0; border-radius: 6px;
          background: #2563eb; color: #fff; font-size: 1rem; cursor: pointer; }}
 .error {{ color: #b91c1c; margin-top: 1rem; }}
</style></head>
<body><div class="card">
 <h1>Sign in to store customer service</h1>
 <form method="post" action="/oauth/authorize">
   <input type="hidden" name="response_type" value="{response_type}">
   <input type="hidden" name="client_id" value="{client_id}">
   <input type="hidden" name="redirect_uri" value="{redirect_uri}">
   <input type="hidden" name="state" value="{state}">
   <label>Username <input type="text" name="username" autofocus required></label>
   <label>Password <input type="password" name="password" required></label>
   <button type="submit">Sign in</button>
   <p class="error">{error}</p>
 </form>
</div></body></html>"""


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_page(response_type: str, client_id: str, redirect_uri: str,
                   state: str = ""):
    _validate_client(client_id, redirect_uri, response_type)
    return HTMLResponse(_LOGIN_PAGE.format(response_type=response_type,
                                           client_id=client_id,
                                           redirect_uri=redirect_uri,
                                           state=state, error=""))


@router.post("/oauth/authorize")
def authorize_submit(response_type: str = Form(...), client_id: str = Form(...),
                     redirect_uri: str = Form(...), state: str = Form(""),
                     username: str = Form(...), password: str = Form(...)):
    _validate_client(client_id, redirect_uri, response_type)

    with Session(sql_engine) as session:
        credential = session.scalar(select(User_Credentials)
                                    .where(User_Credentials.username == username))

    if credential is None or not verify_password(password, credential.password_hash):
        page = _LOGIN_PAGE.format(response_type=response_type, client_id=client_id,
                                  redirect_uri=redirect_uri, state=state,
                                  error="Invalid username or password.")
        return HTMLResponse(page, status_code=401)

    # Purge expired codes, then mint a single-use code (5 minute lifetime).
    now = time.time()
    for code in [c for c, entry in _auth_codes.items() if entry["expires_at"] < now]:
        _auth_codes.pop(code, None)

    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {"customer_id": credential.customer_id,
                         "username": credential.username,
                         "expires_at": now + AUTH_CODE_TTL_SECONDS}

    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={code}"
    if state:
        from urllib.parse import quote
        location += f"&state={quote(state, safe='')}"
    return RedirectResponse(url=location, status_code=302)


@router.post("/oauth/token")
def token(grant_type: str = Form(...), code: str = Form(None),
          redirect_uri: str = Form(None), client_id: str = Form(None),
          refresh_token: str = Form(None)):
    if grant_type == "authorization_code":
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code")
        entry = _auth_codes.pop(code, None)  # single-use: popped on first exchange
        if entry is None:
            raise HTTPException(status_code=400, detail="invalid_grant: unknown or already-used code")
        if entry["expires_at"] < time.time():
            raise HTTPException(status_code=400, detail="invalid_grant: code expired")
        customer_id, username = entry["customer_id"], entry["username"]
        expires_delta = TOKEN_TTL

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="Missing refresh_token")
        payload = _decode_token(refresh_token, "refresh")
        customer_id, username = payload["sub"], payload["username"]
        expires_delta = TOKEN_TTL

    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    access_token = _create_token(customer_id, username, "access", expires_delta)
    refresh = _create_token(customer_id, username, "refresh", TOKEN_TTL * 24 * 7)

    return {"access_token": access_token,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": int(expires_delta.total_seconds())}


# --------------------------------------------------------------------------- #
# Token-introspection style endpoints used by the frontend
# --------------------------------------------------------------------------- #

@router.get("/api/auth/me")
def me(payload: dict = Depends(get_current_user_payload)):
    customer_id = payload["sub"]
    with Session(sql_engine) as session:
        info = session.scalar(select(Customer_info)
                              .where(Customer_info.customer_id == customer_id))
    if info is None:
        raise HTTPException(status_code=404, detail="Customer record not found")
    return {"customer_id": customer_id,
            "username": payload.get("username"),
            "membership_level": info.membership_level,
            "createdts": info.createdts,
            "account_balance": info.account_balance}
