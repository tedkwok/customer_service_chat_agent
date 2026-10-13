import { useCallback, useEffect, useState } from "react";
import { api } from "../auth";

interface Me {
  customer_id: string;
  username: string;
  membership_level: string;
  createdts: string;
  account_balance: number;
}

export default function TopUp() {
  const [me, setMe] = useState<Me | null>(null);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const refresh = useCallback(async () => {
    try {
      const response = await api("/api/auth/me");
      setMe(await response.json());
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setInfo("");
    const value = parseFloat(amount);
    if (!(value > 0)) {
      setError("Enter a positive amount.");
      return;
    }
    try {
      const response = await api("/api/account/topup", {
        method: "POST",
        body: JSON.stringify({ amount: value }),
      });
      const body = await response.json();
      setInfo(`Topped up ${body.amount}. New balance: ${body.new_balance}.`);
      setAmount("");
      refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="card">
      <h1>Account balance</h1>
      {me ? (
        <>
          <p>
            Customer <strong>{me.customer_id}</strong> ({me.username}) —{" "}
            <span className="pill">{me.membership_level}</span>
          </p>
          <p>
            Current balance: <strong>{me.account_balance.toFixed(2)}</strong>
          </p>
          <form onSubmit={submit}>
            <label>
              Top-up amount
              <input
                type="number"
                min="10"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 250.00"
                required
              />
            </label>
            <button type="submit">Add balance</button>
          </form>
        </>
      ) : (
        <p>Loading account…</p>
      )}
      {error && <p className="error">{error}</p>}
      {info && <p className="info">{info}</p>}
    </div>
  );
}
