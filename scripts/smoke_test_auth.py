"""Mock-mode smoke test of the OAuth2 auth server + account top-up (no docker).

Runs the real FastAPI app (routers only — lifespan/event-bus is NOT started)
over httpx.ASGITransport with MYSQL_CONNECTION_URL pointed at a throwaway
SQLite file, then exercises:

  register -> /oauth/authorize (form) -> code -> /oauth/token -> JWT
  -> /api/auth/me -> /api/account/topup -> balance increased
  + negative cases (bad password, code reuse, missing token).

Run:  .venv/bin/python scripts/smoke_test_auth.py
"""

import asyncio
import os
import sys
import tempfile

SQLITE_PATH = os.path.join(tempfile.mkdtemp(prefix="scs_auth_smoke_"), "smoke.db")

# Point the sync engine at SQLite before any app import; keep the async URL
# syntactically valid (its engine is created at import but never connects).
os.environ["MYSQL_CONNECTION_URL"] = f"sqlite:///{SQLITE_PATH}"
os.environ["MYSQL_ASYNC_CONNECTION_URL"] = "mysql+aiomysql://u:p@localhost:3306/none"
os.environ.setdefault("LITELLM_API_KEY", "sk-test-dummy")
os.environ.setdefault("POSTGRES_DATABASE_URL", "postgresql://u:p@localhost:5432/none")
os.environ.setdefault("OAUTH_JWT_SECRET", "smoke-test-secret")
os.environ.setdefault("OAUTH_REDIRECT_URI", "http://localhost:5173/callback")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8001")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.connection.mysql import init_database  # noqa: E402
from app.main import app  # noqa: E402

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


async def main():
    global PASS, FAIL
    init_database()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 follow_redirects=False) as client:
        username = "smoke_alice"
        password = "correct-horse-battery"

        # ---- 1. register ----------------------------------------------------
        r = await client.post("/api/auth/register",
                              json={"username": username, "password": password})
        print("\n[1] register")
        check("201 created", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
        customer_id = r.json().get("customer_id", "")
        check("customer_id minted", customer_id.startswith("cu_"), f"got {customer_id}")

        r2 = await client.post("/api/auth/register",
                               json={"username": username, "password": password})
        check("duplicate username -> 409", r2.status_code == 409, f"got {r2.status_code}")

        # ---- 2. authorization-code flow --------------------------------------
        params = {"response_type": "code", "client_id": "frontend",
                  "redirect_uri": "http://localhost:5173/callback",
                  "state": "xyz-state"}
        r = await client.get("/oauth/authorize", params=params)
        print("\n[2] /oauth/authorize")
        check("login form served", r.status_code == 200 and "<form" in r.text,
              f"got {r.status_code}")

        form = dict(params)
        form.update({"username": username, "password": "wrong-password"})
        r = await client.post("/oauth/authorize", data=form)
        check("wrong password -> 401", r.status_code == 401, f"got {r.status_code}")

        form["password"] = password
        r = await client.post("/oauth/authorize", data=form)
        check("valid login -> 302 redirect", r.status_code == 302, f"got {r.status_code}")
        location = r.headers.get("location", "")
        check("redirect carries code", "code=" in location, f"got {location}")
        check("redirect carries state", "state=xyz-state" in location, f"got {location}")
        code = location.split("code=")[1].split("&")[0]

        r = await client.post("/oauth/authorize", data=form)
        check("second login mints a new code", r.status_code == 302
              and r.headers.get("location", "").split("code=")[-1].split("&")[0] != code)

        # ---- 3. token exchange -------------------------------------------------
        print("\n[3] /oauth/token")
        r = await client.post("/oauth/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "http://localhost:5173/callback", "client_id": "frontend"})
        check("200 token response", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        body = r.json()
        access_token = body.get("access_token", "")
        refresh_token = body.get("refresh_token", "")
        check("access token issued", access_token.count(".") == 2)
        check("bearer type + expiry", body.get("token_type") == "Bearer"
              and body.get("expires_in", 0) > 0)
        import jwt as pyjwt
        import base64, json as _json
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        jwt_payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        check("customer id inside JWT", jwt_payload.get("sub") == customer_id,
              f"got {jwt_payload}")
        decoded = pyjwt.decode(access_token, os.environ["OAUTH_JWT_SECRET"],
                               algorithms=["HS256"])
        check("JWT verifies with secret", decoded.get("sub") == customer_id
              and decoded.get("typ") == "access")

        r2 = await client.post("/oauth/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "http://localhost:5173/callback", "client_id": "frontend"})
        check("code reuse rejected (single-use)", r2.status_code == 400, f"got {r2.status_code}")

        r3 = await client.post("/oauth/token", data={
            "grant_type": "refresh_token", "refresh_token": refresh_token})
        check("refresh grant works", r3.status_code == 200
              and r3.json().get("access_token"), f"got {r3.status_code}")

        # ---- 4. /api/auth/me -----------------------------------------------------
        print("\n[4] /api/auth/me")
        r = await client.get("/api/auth/me")
        check("no token -> 401", r.status_code == 401, f"got {r.status_code}")

        headers = {"authorization": f"Bearer {access_token}"}
        r = await client.get("/api/auth/me", headers=headers)
        check("200 with Bearer", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        me = r.json()
        check("me returns customer_id", me.get("customer_id") == customer_id)
        check("me returns membership+balance",
              me.get("membership_level") == "Basic" and me.get("account_balance") == 0,
              f"got {me}")

        # ---- 5. top-up -------------------------------------------------------------
        print("\n[5] /api/account/topup")
        r = await client.post("/api/account/topup", json={"amount": 250.5},
                              headers=headers)
        check("topup 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        check("balance 250.5", abs(r.json().get("new_balance", 0) - 250.5) < 1e-9,
              f"got {r.json()}")

        r = await client.post("/api/account/topup", json={"amount": 100}, headers=headers)
        check("second topup accumulates", abs(r.json().get("new_balance", 0) - 350.5) < 1e-9,
              f"got {r.json()}")

        r = await client.post("/api/account/topup", json={"amount": -5}, headers=headers)
        check("negative amount rejected", r.status_code == 422, f"got {r.status_code}")

        r = await client.post("/api/account/topup", json={"amount": 5})
        check("topup without token -> 401", r.status_code == 401, f"got {r.status_code}")

    print(f"\n{'='*50}\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
