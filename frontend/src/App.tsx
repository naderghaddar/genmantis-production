import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  CircleHelp,
  Columns3,
  Compass,
  FolderKanban,
  Globe2,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Settings2,
  Sparkles,
  Users,
} from "lucide-react";
import {
  active,
  api,
  auth,
  initializeAuth,
  type Campaign,
  type Config,
  type Plan,
  type Workspace,
} from "./services/workspaceApi";
import { Mark, Modal, Spinner } from "./components/workspace/Shared";
import Overview from "./components/workspace/Overview";
import Advisor from "./components/workspace/Advisor";
import Leads from "./components/workspace/Leads";
import Pipeline from "./components/workspace/Pipeline";
import Campaigns, { CampaignDetail } from "./components/workspace/Campaigns";
import CampaignForm from "./components/workspace/CampaignForm";
import LeadDetail from "./components/workspace/LeadDetail";
import {
  AuthModal,
  BusinessSettings,
  Integrations,
} from "./components/workspace/Settings";

type Page =
  | "overview"
  | "advisor"
  | "leads"
  | "pipeline"
  | "campaigns"
  | "profile"
  | "integrations";
const nav = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "advisor", label: "Research advisor", icon: Sparkles },
  { id: "leads", label: "Lead database", icon: Users },
  { id: "pipeline", label: "Pipeline", icon: Columns3 },
  { id: "campaigns", label: "Campaigns", icon: FolderKanban },
] as const;
const pageNames = {
  overview: "Overview",
  advisor: "Research advisor",
  leads: "Lead database",
  pipeline: "Pipeline",
  campaigns: "Campaigns",
  profile: "Business profile",
  integrations: "Sources & integrations",
};

export default function App() {
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.slice(1);
    return Object.keys(pageNames).includes(hash) ? (hash as Page) : "overview";
  });
  const [config, setConfig] = useState<Config | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editCampaign, setEditCampaign] = useState<Campaign | null>(null);
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(false);
  const [help, setHelp] = useState(false);
  const generation = useRef(0);
  const alive = useRef(true);
  const [leadCampaign, setLeadCampaign] = useState("");
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
              setCampaignId(null);
              setLeadId(null);
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
    const change = () => {
      const value = window.location.hash.slice(1);
      if (Object.keys(pageNames).includes(value)) setPage(value as Page);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  function review(campaign: Campaign) {
    setCampaignId(campaign.id);
  }
  async function saveCampaign(plan: Plan, campaign?: Campaign | null) {
    const saved = campaign
      ? await api<Campaign>(
          "/campaigns/" + campaign.id + "?version=" + campaign.version,
          "PUT",
          plan,
        )
      : await api<Campaign>("/campaigns", "POST", plan);
    await refresh();
    setShowCreate(false);
    setEditCampaign(null);
    setCampaignId(saved.id);
    setPage("campaigns");
  }
  const selectedCampaign = workspace?.campaigns.find(
    (c) => c.id === campaignId,
  );
  const selectedLead = workspace?.leads.find((l) => l.id === leadId);
  const move = (next: Page) => {
    if (next === "leads") setLeadCampaign("");
    setPage(next);
  };
  return (
    <div className="workspace-app">
      {sidebar && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside className={"sidebar " + (sidebar ? "open" : "")}>
        <a
          href="#overview"
          className="brand-lockup"
          onClick={() => move("overview")}
        >
          <Mark />
          <span>
            genmantis<span className="brand-period">.</span>
          </span>
        </a>
        <div className="workspace-switch">
          <span className="workspace-avatar">
            {(workspace?.profile.company_name || "My workspace").slice(0, 1)}
          </span>
          <div>
            <strong>{workspace?.profile.company_name || "My workspace"}</strong>
            <small>
              {workspace?.account.storage === "cloud"
                ? "Cloud workspace"
                : "Local workspace"}
            </small>
          </div>
          <ChevronDown size={14} />
        </div>
        <button
          className="sidebar-create"
          onClick={() => setShowCreate(true)}
          disabled={!workspace}
        >
          <Plus size={16} /> New campaign<span>↗</span>
        </button>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {nav.map((item) => (
            <button
              key={item.id}
              className={"nav-item " + (page === item.id ? "active" : "")}
              onClick={() => move(item.id)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "leads" && !!workspace?.leads.length && (
                <b>{workspace.leads.length}</b>
              )}
              {item.id === "advisor" && <span className="nav-ai">AI</span>}
            </button>
          ))}
        </nav>
        <div className="nav-label second">PREFERENCES</div>
        <nav aria-label="Workspace preferences">
          <button
            className={"nav-item " + (page === "profile" ? "active" : "")}
            onClick={() => move("profile")}
          >
            <Settings2 size={18} />
            <span>Business profile</span>
          </button>
          <button
            className={"nav-item " + (page === "integrations" ? "active" : "")}
            onClick={() => move("integrations")}
          >
            <Globe2 size={18} />
            <span>Sources & integrations</span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="advisor-tip">
            <Compass size={21} />
            <strong>Better leads start with a plan.</strong>
            <p>Let your advisor help you find your next market.</p>
            <button onClick={() => move("advisor")}>
              Explore with AI
              <ArrowRight size={13} />
            </button>
          </div>
          <button className="nav-item" onClick={() => setHelp(true)}>
            <CircleHelp size={17} />
            <span>How it works</span>
          </button>
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
                    : "Local mode"}
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
            <span className="topbar-workspace">Workspace</span>
            <span className="breadcrumb-divider">/</span>
            <strong>{pageNames[page]}</strong>
          </div>
          <div>
            <span className="system-status">
              <i />
              {running ? "Research in progress" : "Your growth, organized"}
            </span>
            <button
              className="help-button"
              aria-label="How GenMantis works"
              onClick={() => setHelp(true)}
            >
              <CircleHelp size={17} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner global-error" role="alert">
            {error}
            <button
              className="text-link"
              onClick={() =>
                void refresh().catch((err) => setError(err.message))
              }
            >
              Retry
            </button>
          </div>
        )}
        {loading ? (
          <div className="app-loading">
            <Mark />
            <Spinner label="Opening your workspace…" />
          </div>
        ) : workspace && config ? (
          <>
            {page === "overview" && (
              <Overview
                workspace={workspace}
                research={() => move("advisor")}
                create={() => setShowCreate(true)}
                leads={() => move("leads")}
                campaigns={() => move("campaigns")}
                review={review}
                openLead={(lead) => setLeadId(lead.id)}
              />
            )}
            {page === "advisor" && (
              <Advisor
                key={workspace.account.email || "local"}
                workspace={workspace}
                refresh={refresh}
                review={review}
                researchAvailable={config.integrations.some((item) => item.name === "OpenAI" && item.connected)}
              />
            )}
            {page === "leads" && (
              <Leads
                key={leadCampaign}
                initialCampaign={leadCampaign}
                workspace={workspace}
                refresh={refresh}
                openLead={(lead) => setLeadId(lead.id)}
                onResearch={() => move("advisor")}
              />
            )}
            {page === "pipeline" && (
              <Pipeline
                workspace={workspace}
                refresh={refresh}
                openLead={(lead) => setLeadId(lead.id)}
                onResearch={() => move("advisor")}
              />
            )}
            {page === "campaigns" && (
              <Campaigns
                workspace={workspace}
                create={() => setShowCreate(true)}
                review={review}
              />
            )}
            {page === "profile" && (
              <BusinessSettings
                key={workspace.account.email || "local"}
                profile={workspace.profile}
                refresh={refresh}
              />
            )}
            {page === "integrations" && <Integrations config={config} />}
          </>
        ) : (
          !error && (
            <div className="app-loading">
              <Mark />
              <h2>Your research workspace awaits</h2>
              <button className="btn-primary" onClick={() => setShowAuth(true)}>
                Sign in to continue
              </button>
            </div>
          )
        )}
      </div>
      {(showCreate || editCampaign) && config && (
        <CampaignForm
          config={config}
          campaign={editCampaign}
          onClose={() => {
            setShowCreate(false);
            setEditCampaign(null);
          }}
          onSave={saveCampaign}
        />
      )}
      {selectedCampaign && (
        <CampaignDetail
          campaign={selectedCampaign}
          onClose={() => setCampaignId(null)}
          refresh={refresh}
          edit={() => {
            setEditCampaign(selectedCampaign);
            setCampaignId(null);
          }}
          showLeads={() => {
            setLeadCampaign(selectedCampaign.id);
            setCampaignId(null);
            setPage("leads");
          }}
        />
      )}
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
      {help && (
        <Modal
          title="From research to relationships"
          onClose={() => setHelp(false)}
        >
          <div className="help-content">
            <p>
              <strong>1. Add your business context.</strong> Tell your advisor
              what you sell, who you serve, and which businesses to avoid.
            </p>
            <p>
              <strong>2. Research with your advisor.</strong> Compare markets,
              inspect company evidence, and prepare a focused campaign.
            </p>
            <p>
              <strong>3. Review and start.</strong> Choose a discovery source
              and a business limit. Starting a campaign uses your connected
              provider accounts.
            </p>
            <p>
              <strong>4. Work your leads.</strong> Hunter finds contacts,
              NeverBounce verifies them, and the CRM organizes the results. Move
              leads through your pipeline, add notes, and plan follow-ups.
            </p>
            <p className="muted">
              Verified means NeverBounce returned valid. Research fit is a
              separate assessment. No outreach is sent automatically.
            </p>
            <button
              className="btn-primary"
              onClick={() => {
                setHelp(false);
                move("advisor");
              }}
            >
              Open research advisor
              <ArrowRight size={15} />
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
