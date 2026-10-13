import { randomState } from "../auth";

// OAuth2 authorization-code flow: redirect to the store's own authorization
// server; it shows the login form and redirects back to /callback?code=...
export default function Login() {
  const start = () => {
    const redirectUri = `${window.location.origin}/callback`;
    const state = randomState();
    sessionStorage.setItem("scs_oauth_state", state);
    const params = new URLSearchParams({
      response_type: "code",
      client_id: "frontend",
      redirect_uri: redirectUri,
      state,
    });
    window.location.href = `/oauth/authorize?${params.toString()}`;
  };

  return (
    <div className="card">
      <h1>Log in</h1>
      <p>Sign in with your Meridian Store account (OAuth2).</p>
      <button onClick={start}>Continue to sign-in</button>
    </div>
  );
}
