import { useState } from "react";
import { Link } from "react-router-dom";

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [created, setCreated] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setCreated("");
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status}: ${text}`);
      }
      const body = await response.json();
      setCreated(`Account created (customer id ${body.customer_id}). You can log in now.`);
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="card">
      <h1>Create account</h1>
      <form onSubmit={submit}>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)}
                 minLength={3} maxLength={50} required />
        </label>
        <label>
          Password (min 8 chars)
          <input type="password" value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 minLength={8} maxLength={128} required />
        </label>
        <button type="submit">Create account</button>
        {error && <p className="error">{error}</p>}
        {created && (
          <p className="info">
            {created} <Link to="/login">Go to login</Link>
          </p>
        )}
      </form>
    </div>
  );
}
