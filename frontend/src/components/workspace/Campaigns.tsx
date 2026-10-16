import {
  ArrowRight,
  Copy,
  FolderKanban,
  MapPin,
  Pause,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import {
  active,
  api,
  type Campaign,
  type Workspace,
  dateLabel,
  sourceName,
} from "../../services/workspaceApi";
import { Badge, Empty, Modal } from "./Shared";

export function CampaignDetail({
  campaign,
  onClose,
  refresh,
  edit,
  showLeads,
}: {
  campaign: Campaign;
  onClose: () => void;
  refresh: () => Promise<void>;
  edit: () => void;
  showLeads: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function act(action: "start" | "cancel" | "duplicate") {
    setBusy(true);
    setError("");
    try {
      if (action === "duplicate") {
        await api("/campaigns", "POST", {
          ...campaign.plan,
          name: campaign.plan.name.slice(0, 110) + " · Copy",
        });
        await refresh();
        onClose();
      } else {
        const result = await api<{ message?: string }>(
          "/campaigns/" + campaign.id + "/" + action,
          "POST",
          action === "start" ? { version: campaign.version } : {},
        );
        if (action === "cancel") setNotice(result.message || "Stop requested.");
        await refresh();
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Campaign overview" onClose={onClose} wide>
      <div className="campaign-detail">
        <div className="campaign-detail-title">
          <span className="campaign-icon">
            <FolderKanban size={23} />
          </span>
          <div>
            <h2>{campaign.plan.name}</h2>
            <p>
              {sourceName(campaign.plan.source)} · Created{" "}
              {dateLabel(campaign.created_at)}
            </p>
          </div>
          <Badge value={campaign.status}>
            {campaign.status.replaceAll("_", " ")}
          </Badge>
        </div>
        <p className="campaign-rationale">
          {campaign.plan.rationale ||
            "A focused search for " + campaign.plan.niche + "."}
        </p>
        <div className="campaign-facts">
          <div>
            <small>DISCOVERY SOURCE</small>
            <strong>{sourceName(campaign.plan.source)}</strong>
          </div>
          <div>
            <small>TARGET</small>
            <strong>{campaign.plan.niche}</strong>
          </div>
          <div>
            <small>LOCATION</small>
            <strong>
              {[campaign.plan.city, campaign.plan.state]
                .filter(Boolean)
                .join(", ") || "Defined by research query"}
            </strong>
          </div>
          <div>
            <small>ENRICHMENT LIMIT</small>
            <strong>{campaign.plan.max_leads} businesses</strong>
          </div>
        </div>
        {campaign.plan.query && (
          <div className="detail-section">
            <h3>Research query</h3>
            <p>{campaign.plan.query}</p>
          </div>
        )}
        {!!campaign.plan.websites.length && (
          <div className="detail-section">
            <h3>Company websites</h3>
            <p className="website-list">{campaign.plan.websites.join("\n")}</p>
          </div>
        )}
        <div className="form-grid">
          <div className="detail-section">
            <h3>Qualification criteria</h3>
            {campaign.plan.qualification_criteria.length ? (
              campaign.plan.qualification_criteria.map((v) => (
                <p key={v}>• {v}</p>
              ))
            ) : (
              <p className="muted">Match the target category and location.</p>
            )}
          </div>
          <div className="detail-section">
            <h3>Exclusions</h3>
            {campaign.plan.exclusions.length ? (
              campaign.plan.exclusions.map((v) => <p key={v}>• {v}</p>)
            ) : (
              <p className="muted">No additional exclusions.</p>
            )}
          </div>
        </div>
        {(campaign.plan.min_google_maps_rank ||
          campaign.plan.max_google_maps_rank) && (
          <p className="muted">
            Maps positions: {campaign.plan.min_google_maps_rank || 1} to{" "}
            {campaign.plan.max_google_maps_rank || "any"}. Unknown ranking
            evidence cannot qualify.
          </p>
        )}
        <div className="verification-note">
          <ShieldCheck size={20} />
          <span>
            {campaign.plan.research_websites
              ? "Company research → fit assessment → "
              : ""}
            Hunter contacts → NeverBounce verification → your CRM.
          </span>
        </div>
        {campaign.status === "draft" ? (
          <div className="execution-note">
            <strong>Before you start</strong>
            <p>
              This starts provider work using your connected accounts. Up to{" "}
              {campaign.plan.max_leads} businesses will be enriched.{" "}
              {campaign.plan.source === "google_maps" &&
                "Apify examines up to 30 source places. "}
              {campaign.plan.research_websites &&
                "Website research can use two model requests per business. "}
              Provider charges vary; no result count is guaranteed.
            </p>
          </div>
        ) : (
          <>
            <div className="campaign-result-grid">
              {[
                ["Discovered", campaign.progress.discovered],
                ["Verified", campaign.progress.verified],
                ["Review", campaign.progress.review],
                ["Already in CRM", campaign.progress.reused],
              ].map(([label, value]) => (
                <div key={label}>
                  <strong>{value}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>
            <p className="run-message">{campaign.message}</p>
            {active(campaign) && (
              <div className="progress-track">
                <span
                  style={{
                    width:
                      Math.max(
                        5,
                        campaign.progress.discovered
                          ? (campaign.progress.processed /
                              campaign.progress.discovered) *
                              100
                          : 8,
                      ) + "%",
                  }}
                />
              </div>
            )}
            {campaign.warnings.map((warning, i) => (
              <p key={i} className="detail-warning">
                {warning}
              </p>
            ))}
            {!!campaign.events.length && (
              <details className="campaign-events">
                <summary>
                  Research activity · {campaign.events.length} updates
                </summary>
                {campaign.events
                  .slice(-12)
                  .reverse()
                  .map((event, i) => (
                    <p key={i}>
                      <time>
                        {new Date(event.at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                      {event.message}
                    </p>
                  ))}
              </details>
            )}
          </>
        )}
        {notice && (
          <p role="status" className="notice-banner">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        <div className="modal-actions">
          {campaign.status === "draft" ? (
            <>
              <button className="btn-secondary" onClick={edit}>
                <Pencil size={14} /> Edit plan
              </button>
              <button
                className="btn-primary"
                disabled={busy}
                onClick={() => void act("start")}
              >
                <Play size={15} />
                {busy ? "Starting…" : "Start campaign"}
              </button>
            </>
          ) : (
            <>
              {active(campaign) ? (
                <button
                  className="btn-secondary"
                  disabled={busy}
                  onClick={() => void act("cancel")}
                >
                  <Pause size={14} /> Stop campaign
                </button>
              ) : (
                <button
                  className="btn-secondary"
                  disabled={busy}
                  onClick={() => void act("duplicate")}
                >
                  <Copy size={14} /> Duplicate plan
                </button>
              )}
              <button className="btn-primary" onClick={showLeads}>
                View leads
                <ArrowRight size={15} />
              </button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

export default function Campaigns({
  workspace,
  create,
  review,
}: {
  workspace: Workspace;
  create: () => void;
  review: (campaign: Campaign) => void;
}) {
  const [filter, setFilter] = useState("all");
  const items = workspace.campaigns.filter(
    (c) =>
      filter === "all" ||
      (filter === "active" ? active(c) : c.status === filter),
  );
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <p className="overline">FOCUSED RESEARCH. BETTER PROSPECTS.</p>
          <h1>Campaigns</h1>
          <p>From a targeting hypothesis to a list of verified contacts.</p>
        </div>
        <button className="btn-primary" onClick={create}>
          <Plus size={16} /> New campaign
        </button>
      </div>
      <div className="lead-tabs">
        {["all", "draft", "active", "completed"].map((value) => (
          <button
            key={value}
            className={filter === value ? "active" : ""}
            onClick={() => setFilter(value)}
          >
            {value === "all"
              ? "All campaigns"
              : value.charAt(0).toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      {items.length ? (
        <div className="campaign-grid">
          {items.map((campaign) => (
            <button
              className="campaign-card"
              key={campaign.id}
              onClick={() => review(campaign)}
            >
              <div className="campaign-card-top">
                <span className="campaign-icon">
                  <FolderKanban size={20} />
                </span>
                <Badge value={campaign.status}>{campaign.status}</Badge>
              </div>
              <h3>{campaign.plan.name}</h3>
              <p>
                {campaign.plan.rationale ||
                  "Discover " +
                    campaign.plan.niche +
                    " and find verified company contacts."}
              </p>
              <div className="campaign-meta">
                <span>
                  <MapPin size={13} />
                  {[campaign.plan.city, campaign.plan.state]
                    .filter(Boolean)
                    .join(", ") || "Web research"}
                </span>
                <span>{sourceName(campaign.plan.source)}</span>
              </div>
              <div className="campaign-card-stats">
                <div>
                  <strong>{campaign.progress.discovered}</strong>
                  <small>Discovered</small>
                </div>
                <div>
                  <strong>{campaign.progress.verified}</strong>
                  <small>Verified</small>
                </div>
                <div>
                  <strong>{campaign.plan.max_leads}</strong>
                  <small>Limit</small>
                </div>
              </div>
              <footer>
                <span>{dateLabel(campaign.created_at)}</span>
                <span>
                  {campaign.status === "draft"
                    ? "Review plan"
                    : "View campaign"}
                  <ArrowRight size={13} />
                </span>
              </footer>
            </button>
          ))}
        </div>
      ) : (
        <div className="data-card">
          <Empty
            icon={<FolderKanban size={28} />}
            title={
              workspace.campaigns.length
                ? "No campaigns in this view"
                : "Give your next search a direction"
            }
            text="Create a campaign yourself, or let your research advisor help define the right businesses, sources and criteria."
            action={
              <button className="btn-primary" onClick={create}>
                <Plus size={15} /> Create a campaign
              </button>
            }
          />
        </div>
      )}
    </div>
  );
}
