import { Navigate, Route, Routes, Link, useNavigate } from "react-router-dom";
import { loadSession, clearSession } from "./auth";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Callback from "./pages/Callback";
import TopUp from "./pages/TopUp";
import Chat from "./pages/Chat";

function RequireAuth({ children }: { children: React.ReactElement }) {
  if (!loadSession()) return <Navigate to="/login" replace />;
  return children;
}

function Nav() {
  const session = loadSession();
  const navigate = useNavigate();
  return (
    <nav className="nav">
      <span className="brand">Meridian Store</span>
      {session ? (
        <>
          <Link to="/topup">Top up</Link>
          <Link to="/chat">Agent chat</Link>
          <span className="whoami">{session.username}</span>
          <button
            onClick={() => {
              clearSession();
              navigate("/login");
            }}
          >
            Log out
          </button>
        </>
      ) : (
        <>
          <Link to="/login">Log in</Link>
          <Link to="/register">Create account</Link>
        </>
      )}
    </nav>
  );
}

export default function App() {
  return (
    <>
      <Nav />
      <main className="page">
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/callback" element={<Callback />} />
          <Route
            path="/topup"
            element={
              <RequireAuth>
                <TopUp />
              </RequireAuth>
            }
          />
          <Route
            path="/chat"
            element={
              <RequireAuth>
                <Chat />
              </RequireAuth>
            }
          />
        </Routes>
      </main>
    </>
  );
}
