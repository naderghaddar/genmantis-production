import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Compass,
  FolderKanban,
  Layers3,
  Plus,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  Globe2,
} from "lucide-react";
import {
  active,
  type Campaign,
  type CRMLead,
  type Workspace,
  dateLabel,
  sourceName,
} from "../../services/workspaceApi";
import { Badge } from "./Shared";

export default function Overview({
  workspace,
  research,
  create,
  leads,
  campaigns,
  review,
  openLead,
}: {
  workspace: Workspace;
  research: () => void;
  create: () => void;
  leads: () => void;
  campaigns: () => void;
  review: (c: Campaign) => void;
  openLead: (l: CRMLead) => void;
}) {
  const verified = workspace.leads.filter(
    (l) => l.category === "verified",
  ).length;
  const qualified = workspace.leads.filter((l) =>
    ["qualified", "contacted", "meeting", "won"].includes(l.stage),
  ).length;
  const running = workspace.campaigns.filter(active).length;
  const recent = workspace.leads.slice(0, 5);
  const hour = new Date().getHours();
  const greeting =
    hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  return (
    <div className="page-content overview-page">
      <div className="page-heading">
        <div>
          <p className="overline">YOUR GROWTH WORKSPACE</p>
          <h1>
            {greeting}
            {workspace.profile.company_name
              ? ", " + workspace.profile.company_name
              : ""}
            <span className="greeting-dot">.</span>
          </h1>
          <p>A clear view of your research, leads, and next opportunities.</p>
        </div>
        <button className="btn-primary" onClick={create}>
          <Plus size={16} /> New campaign
        </button>
      </div>
      <section className="overview-hero">
        <div className="hero-copy">
          <span className="hero-eyebrow">
            <Sparkles size={13} /> MEET YOUR RESEARCH PARTNER
          </span>
          <h2>
            Find the right companies.
            <br />
            <span>Start better conversations.</span>
          </h2>
          <p>
            Your AI advisor connects your business goals to real market
            evidence—and a pipeline of verified contacts.
          </p>
          <button className="btn-dark" onClick={research}>
            Start a conversation
            <ArrowUpRight size={16} />
          </button>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="orbit-center">
            <Compass size={38} />
          </div>
          <div className="floating-chip chip-market">
            <Globe2 size={17} />
            <span>Market research</span>
            <Check size={13} />
          </div>
          <div className="floating-chip chip-fit">
            <Target size={17} />
            <span>Customer fit</span>
            <Check size={13} />
          </div>
          <div className="floating-chip chip-verified">
            <ShieldCheck size={17} />
            <span>Verified contacts</span>
            <Check size={13} />
          </div>
          <span className="orbit-dot dot-one" />
          <span className="orbit-dot dot-two" />
        </div>
      </section>
      <div className="metric-grid">
        {[
          {
            label: "Total companies",
            value: workspace.leads.length,
            sub: "In your lead database",
            icon: <Users size={18} />,
          },
          {
            label: "Verified contacts",
            value: verified,
            sub: "Checked by NeverBounce",
            icon: <ShieldCheck size={18} />,
          },
          {
            label: "In your pipeline",
            value: qualified,
            sub: "Qualified and progressing",
            icon: <Layers3 size={18} />,
          },
          {
            label: "Active campaigns",
            value: running,
            sub: workspace.campaigns.length + " campaigns in total",
            icon: <Compass size={18} />,
          },
        ].map((metric) => (
          <div className="metric-card" key={metric.label}>
            <div>
              <span>{metric.label}</span>
              {metric.icon}
            </div>
            <strong>{metric.value.toLocaleString()}</strong>
            <small>{metric.sub}</small>
          </div>
        ))}
      </div>
      <div className="overview-columns">
        <section className="data-card">
          <div className="card-heading">
            <div>
              <h3>Recent campaigns</h3>
              <p>Your research, in motion.</p>
            </div>
            <button className="text-link" onClick={campaigns}>
              View all
              <ArrowRight size={13} />
            </button>
          </div>
          {workspace.campaigns.length ? (
            <div className="recent-campaigns">
              {workspace.campaigns.slice(0, 4).map((c) => (
                <button key={c.id} onClick={() => review(c)}>
                  <span className="campaign-icon">
                    <FolderKanban size={18} />
                  </span>
                  <span>
                    <strong>{c.plan.name}</strong>
                    <small>
                      {sourceName(c.plan.source)} · {dateLabel(c.created_at)}
                    </small>
                  </span>
                  <Badge value={c.status}>{c.status}</Badge>
                  <ArrowRight size={15} />
                </button>
              ))}
            </div>
          ) : (
            <div className="campaign-empty">
              <span className="empty-icon">
                <FolderKanban size={25} />
              </span>
              <h3>Your first campaign is a conversation away</h3>
              <p>
                Share who you want to reach. Your advisor will help you make a
                plan.
              </p>
              <button className="text-link" onClick={research}>
                Explore with your advisor
                <ArrowRight size={14} />
              </button>
            </div>
          )}
        </section>
        <section className="workflow-card">
          <p className="overline">FROM INSIGHT TO OPPORTUNITY</p>
          <h3>
            A thoughtful path
            <br />
            to your next customer.
          </h3>
          <div className="workflow-step">
            <span>01</span>
            <div>
              <strong>Understand your business</strong>
              <p>Your offer, ideal customer, and goals.</p>
            </div>
          </div>
          <div className="workflow-step">
            <span>02</span>
            <div>
              <strong>Research the right companies</strong>
              <p>Choose sources and collect evidence.</p>
            </div>
          </div>
          <div className="workflow-step">
            <span>03</span>
            <div>
              <strong>Connect with confidence</strong>
              <p>Hunter contacts, verified by NeverBounce.</p>
            </div>
          </div>
          <div className="workflow-footer">
            <ShieldCheck size={15} /> Every verified badge has a source.
          </div>
        </section>
      </div>
      <section className="data-card overview-leads">
        <div className="card-heading">
          <div>
            <h3>Recently discovered</h3>
            <p>Fresh research for your next conversation.</p>
          </div>
          <button className="text-link" onClick={leads}>
            Open lead database
            <ArrowRight size={13} />
          </button>
        </div>
        {recent.length ? (
          <div className="table-overflow">
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Industry</th>
                  <th>Verification</th>
                  <th>Added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {recent.map((l) => (
                  <tr key={l.id}>
                    <td>
                      <button
                        className="company-cell"
                        onClick={() => openLead(l)}
                      >
                        <span className="company-avatar">
                          {l.company.slice(0, 2).toUpperCase()}
                        </span>
                        <span>
                          <strong>{l.company}</strong>
                          <small>{l.domain}</small>
                        </span>
                      </button>
                    </td>
                    <td>{l.industry}</td>
                    <td>
                      <Badge value={l.category} />
                    </td>
                    <td className="muted">{dateLabel(l.created_at)}</td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={"Open " + l.company}
                        onClick={() => openLead(l)}
                      >
                        <ArrowUpRight size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="inline-empty">
            <Users size={20} />
            <span>
              Your discovered companies will appear here. Ready when you are.
            </span>
            <button className="text-link" onClick={research}>
              Find leads
              <ArrowRight size={14} />
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
