import { useState, type FormEvent } from "react";
import { Check, Globe2, Save, ShieldCheck } from "lucide-react";
import {
  api,
  auth,
  type Config,
  type Profile,
} from "../../services/workspaceApi";
import { Modal } from "./Shared";

export function BusinessSettings({
  profile,
  refresh,
}: {
  profile: Profile;
  refresh: () => Promise<void>;
}) {
  const [value, setValue] = useState(profile);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await api("/profile", "PUT", value);
      await refresh();
      setStatus(
        "Business profile saved. Your advisor will use this context in future messages.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const field = (
    key: keyof Profile,
    label: string,
    placeholder: string,
    area = false,
  ) => (
    <label>
      {label}
      {area ? (
        <textarea
          rows={3}
          value={value[key]}
          maxLength={key === "exclusions" ? 2000 : 3000}
          placeholder={placeholder}
          onChange={(e) => {
            setValue({ ...value, [key]: e.target.value });
            setStatus("");
          }}
        />
      ) : (
        <input
          value={value[key]}
          maxLength={
            ["website", "buyer_roles"].includes(key)
              ? 500
              : key === "geography"
                ? 300
                : 200
          }
          placeholder={placeholder}
          onChange={(e) => {
            setValue({ ...value, [key]: e.target.value });
            setStatus("");
          }}
        />
      )}
    </label>
  );
  return (
    <div className="page-content settings-page">
      <div className="page-heading">
        <div>
          <p className="overline">BETTER CONTEXT. BETTER RECOMMENDATIONS.</p>
          <h1>Your business profile</h1>
          <p>Teach your advisor what a great customer looks like for you.</p>
        </div>
      </div>
      <form className="settings-card" onSubmit={save}>
        <div className="settings-intro">
          <Globe2 size={22} />
          <div>
            <h3>The business behind the search</h3>
            <p>
              This context carries across research conversations and campaigns.
            </p>
          </div>
        </div>
        <div className="form-grid">
          {field("company_name", "Company name", "Your business name")}
          {field("website", "Company website", "https://yourcompany.com")}
        </div>
        {field(
          "offer",
          "What do you sell?",
          "Describe your product or service, the problem it solves, and what makes it different.",
          true,
        )}
        {field(
          "ideal_customer",
          "Who is your ideal customer?",
          "Company type, size, current challenges, and examples of customers you serve well.",
          true,
        )}
        <div className="form-grid">
          {field(
            "deal_size",
            "Typical deal size",
            "e.g. $2,000–$5,000 per month",
          )}
          {field(
            "geography",
            "Markets you serve",
            "e.g. Canada and the United States",
          )}
        </div>
        {field(
          "buyer_roles",
          "Who typically buys?",
          "e.g. Owner, head of marketing, operations director",
        )}
        {field(
          "exclusions",
          "Who should we avoid?",
          "e.g. Existing customers, franchises, businesses outside our service area.",
          true,
        )}
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {status && (
          <p className="notice-banner" role="status">
            <Check size={15} />
            {status}
          </p>
        )}
        <div className="modal-actions">
          <button className="btn-primary" disabled={busy}>
            <Save size={15} />
            {busy ? "Saving…" : "Save profile"}
          </button>
        </div>
      </form>
    </div>
  );
}
export function Integrations({ config }: { config: Config }) {
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <p className="overline">YOUR RESEARCH TOOLKIT</p>
          <h1>Sources & integrations</h1>
          <p>
            Purpose-built discovery, company research, and contact verification.
          </p>
        </div>
      </div>
      <div className="integration-grid">
        {config.integrations.map((item) => (
          <article className="integration-card" key={item.name}>
            <div className="integration-top">
              <span className="provider-logo">{item.name.slice(0, 1)}</span>
              <span
                className={
                  "connection-status " + (item.connected ? "connected" : "")
                }
              >
                <i />
                {item.connected ? "Configured" : "Not configured"}
              </span>
            </div>
            <h3>{item.name}</h3>
            <p>{item.purpose}</p>
            <small>
              {item.connected
                ? "Credentials are configured. Provider access and available credits are checked when used."
                : "Ask your workspace administrator to connect this provider."}
            </small>
          </article>
        ))}
      </div>
      <h2 className="section-heading">Discovery capabilities</h2>
      <div className="source-catalog">
        {config.sources.map((source) => (
          <article className="data-card" key={source.id}>
            <h3>
              {source.name}
              <span className="subtle">{source.provider}</span>
            </h3>
            <p>{source.description}</p>
            <div className="field-tags">
              {source.fields.map((f) => (
                <span key={f}>{f}</span>
              ))}
            </div>
            <small>{source.limits}</small>
          </article>
        ))}
      </div>
      <div className="verification-note">
        <ShieldCheck size={22} />
        <span>
          Verification is consistent across all sources. Hunter discovers the
          contact; NeverBounce checks the email. Unverified contacts remain
          clearly labeled and are excluded from verified exports.
        </span>
      </div>
    </div>
  );
}

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
