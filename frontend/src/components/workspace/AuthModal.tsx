import { useState, type FormEvent } from "react";
import { auth } from "../../services/workspaceApi";
import { Modal } from "./Shared";

export function AuthModal({
  onClose,
  required,
}: {
  onClose: () => void;
  required?: boolean;
}) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!auth) return;
    setBusy(true);
    setError("");
    try {
      const result =
        mode === "signin"
          ? await auth.auth.signInWithPassword({ email, password })
          : await auth.auth.signUp({ email, password });
      if (result.error) throw result.error;
      if (result.data.session) onClose();
      else setNotice("Check your email to confirm your account, then sign in.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        mode === "signin" ? "Welcome to GenMantis" : "Create your workspace"
      }
      onClose={onClose}
    >
      <form className="auth-form" onSubmit={submit}>
        <p className="muted">
          {required
            ? "Sign in to access your research workspace."
            : "Sign in to keep your leads, campaigns and research in your cloud workspace. Local records stay in your separate local workspace."}
        </p>
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={
              mode === "signin" ? "current-password" : "new-password"
            }
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="notice-banner" role="status">
            {notice}
          </p>
        )}
        <button className="btn-primary" disabled={busy || !auth}>
          {busy
            ? "Please wait…"
            : mode === "signin"
              ? "Sign in"
              : "Create account"}
        </button>
        <button
          type="button"
          className="text-link"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError("");
            setNotice("");
          }}
        >
          {mode === "signin"
            ? "New here? Create an account"
            : "Already have an account? Sign in"}
        </button>
      </form>
    </Modal>
  );
}
