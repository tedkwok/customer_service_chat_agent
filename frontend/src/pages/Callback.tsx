import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { saveSession } from "../auth";

// OAuth2 redirect target: exchange the authorization code for tokens.
export default function Callback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state") || "";
    const expected = sessionStorage.getItem("scs_oauth_state");

    if (!code) {
      setError("No authorization code in the redirect URL.");
      return;
    }
    if (expected && state !== expected) {
      setError("OAuth state mismatch — possible CSRF, aborting.");
      return;
    }

    (async () => {
      try {
        const response = await fetch("/oauth/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            grant_type: "authorization_code",
            code,
            redirect_uri: `${window.location.origin}/callback`,
            client_id: "frontend",
          }),
        });
        if (!response.ok) {
          throw new Error(`${response.status}: ${await response.text()}`);
        }
        const tokens = await response.json();

        // The /me endpoint gives the identity the token carries.
        const meResponse = await fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${tokens.access_token}` },
        });
        if (!meResponse.ok) {
          throw new Error(`${meResponse.status}: ${await meResponse.text()}`);
        }
        const me = await meResponse.json();

        saveSession({
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
          customer_id: me.customer_id,
          username: me.username,
        });
        sessionStorage.removeItem("scs_oauth_state");
        navigate("/chat");
      } catch (err) {
        setError(String(err));
      }
    })();
  }, [params, navigate]);

  return (
    <div className="card">
      <h1>Completing sign-in…</h1>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
