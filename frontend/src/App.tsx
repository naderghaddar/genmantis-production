import { useCallback, useEffect, useRef, useState } from "react";
import { LogOut, Menu, Sparkles, Users } from "lucide-react";
import {
  active,
  api,
  auth,
  initializeAuth,
  type Config,
  type Workspace,
} from "./services/workspaceApi";
import { Mark, Spinner } from "./components/workspace/Shared";
import Advisor from "./components/workspace/Advisor";
import Leads from "./components/workspace/Leads";
import LeadDetail from "./components/workspace/LeadDetail";
import { AuthModal } from "./components/workspace/AuthModal";

type Page = "advisor" | "leads";
export default function App() {
  const [page, setPage] = useState<Page>(() =>
    window.location.hash === "#leads" ? "leads" : "advisor",
  );
  const [config, setConfig] = useState<Config | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(false);
  const [leadSearch, setLeadSearch] = useState("");
  const generation = useRef(0);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    const current = generation.current;
    const next = await api<Workspace>("");
    if (alive.current && current === generation.current) {
      setWorkspace(next);
      setError("");
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;
    void (async () => {
      try {
        const cfg = await api<Config>("/config");
        if (cancelled) return;
        setConfig(cfg);
        const client = initializeAuth(cfg);
        const session = client
          ? (await client.auth.getSession()).data.session
          : null;
        if (cancelled) return;
        if (!session && !cfg.auth.local_enabled) {
          setAuthRequired(true);
          setShowAuth(true);
        } else await refresh();
        if (client && !cancelled) {
          const subscription = client.auth.onAuthStateChange((event) => {
            if (event === "SIGNED_IN" || event === "SIGNED_OUT") {
              generation.current += 1;
              setWorkspace(null);
              setLeadId(null);
              setPage("advisor");
              setLeadSearch("");
              setAuthRequired(
                event === "SIGNED_OUT" && !cfg.auth.local_enabled,
              );
              setTimeout(() => {
                if (
                  !cancelled &&
                  (event === "SIGNED_IN" || cfg.auth.local_enabled)
                )
                  void refresh().catch((err) => setError(err.message));
              }, 0);
            }
          });
          unsubscribe = () => subscription.data.subscription.unsubscribe();
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      alive.current = false;
      unsubscribe?.();
    };
  }, [refresh]);
  const running = workspace?.campaigns.some(active);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(
      () => void refresh().catch((err) => setError(err.message)),
      4000,
    );
    return () => clearInterval(timer);
  }, [running, refresh]);
  useEffect(() => {
    window.location.hash = page;
    setSidebar(false);
  }, [page]);
  useEffect(() => {
    const change = () =>
      setPage(window.location.hash === "#leads" ? "leads" : "advisor");
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  const selectedLead = workspace?.leads.find((lead) => lead.id === leadId);
  return (
    <div className="workspace-app focused-workspace">
      {sidebar && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside className={"sidebar " + (sidebar ? "open" : "")}>
        <a
          href="#advisor"
          className="brand-lockup"
          onClick={() => setPage("advisor")}
        >
          <Mark />
          <span>
            genmantis<span className="brand-period">.</span>
          </span>
        </a>
        <p className="focused-tagline">Your SEO growth partner</p>
        <nav aria-label="Main navigation">
          <button
            className={"nav-item " + (page === "advisor" ? "active" : "")}
            onClick={() => setPage("advisor")}
          >
            <Sparkles size={18} />
            <span>Research advisor</span>
          </button>
          <button
            className={"nav-item " + (page === "leads" ? "active" : "")}
            onClick={() => {
              setLeadSearch("");
              setPage("leads");
            }}
          >
            <Users size={18} />
            <span>Lead database</span>
            {!!workspace?.leads.length && <b>{workspace.leads.length}</b>}
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="advisor-tip">
            <Sparkles size={21} />
            <strong>Tell your agent who to find.</strong>
            <p>
              Choose your niche, cities and number of leads. GenMantis handles
              the research.
            </p>
          </div>
          <div className="account-row">
            <span className="account-avatar">
              {(workspace?.account.email || "You").slice(0, 1).toUpperCase()}
            </span>
            <button onClick={() => config?.auth.url && setShowAuth(true)}>
              <strong>
                {workspace?.account.email?.split("@")[0] || "Your workspace"}
              </strong>
              <small>
                {workspace?.account.storage === "cloud"
                  ? "Signed in"
                  : config?.auth.url
                    ? "Sign in for cloud storage"
                    : "Local workspace"}
              </small>
            </button>
            {workspace?.account.storage === "cloud" && (
              <button
                aria-label="Sign out"
                className="icon-button"
                onClick={() => void auth?.auth.signOut()}
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="main-workspace">
        <header className="topbar">
          <div>
            <button
              className="icon-button mobile-menu"
              onClick={() => setSidebar(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <strong>
              {page === "advisor" ? "Research advisor" : "Lead database"}
            </strong>
          </div>
          <span className="system-status">
            <i />
            {running ? "Finding your next leads" : "Built for SEO outreach"}
          </span>
        </header>
        {error && (
          <div className="error-banner global-error" role="alert">
            {error}
            <button
              className="text-link"
              onClick={() =>
                config
                  ? void refresh().catch((err) => setError(err.message))
                  : window.location.reload()
              }
            >
              Retry
            </button>
          </div>
        )}
        {loading ? (
          <div className="app-loading">
            <Mark />
            <Spinner label="Opening your agent…" />
          </div>
        ) : workspace && config ? (
          <>
            <div hidden={page !== "advisor"}>
              <Advisor
                key={workspace.account.email || "local"}
                workspace={workspace}
                refresh={refresh}
                review={(campaign) => {
                  setLeadSearch(campaign.id);
                  setPage("leads");
                }}
                researchAvailable={config.integrations.some(
                  (item) => item.name === "OpenAI" && item.connected,
                )}
              />
            </div>
            {page === "leads" && (
              <Leads
                key={leadSearch}
                initialCampaign={leadSearch}
                workspace={workspace}
                refresh={refresh}
                openLead={(lead) => setLeadId(lead.id)}
                onResearch={() => setPage("advisor")}
              />
            )}
          </>
        ) : (
          !error && (
            <div className="app-loading">
              <Mark />
              <h2>Your GenMantis agent awaits</h2>
              <button className="btn-primary" onClick={() => setShowAuth(true)}>
                Sign in to continue
              </button>
            </div>
          )
        )}
      </div>
      {selectedLead && (
        <LeadDetail
          key={selectedLead.id}
          lead={selectedLead}
          onClose={() => setLeadId(null)}
          onSaved={refresh}
        />
      )}
      {showAuth && (
        <AuthModal required={authRequired} onClose={() => setShowAuth(false)} />
      )}
    </div>
  );
}
