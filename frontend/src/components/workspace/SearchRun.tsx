import { useState } from "react";
import { ArrowRight, Check, MapPin, Square, Target } from "lucide-react";
import { active, api, type Campaign } from "../../services/workspaceApi";
import { ExternalLink, Spinner } from "./Shared";

export default function SearchRun({
  campaign,
  refresh,
  viewLeads,
  suggest,
}: {
  campaign: Campaign;
  refresh: () => Promise<void>;
  viewLeads: () => void;
  suggest: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stopping, setStopping] = useState(false);
  const target = campaign.progress.target ?? campaign.plan.max_leads;
  const found = campaign.progress.verified;
  const running = active(campaign);
  const locations = campaign.plan.locations?.length
    ? campaign.plan.locations
    : [{ city: campaign.plan.city, state: campaign.plan.state }];
  async function action(kind: "start" | "cancel") {
    setBusy(true);
    setError("");
    try {
      await api(
        "/campaigns/" + campaign.id + "/" + kind,
        "POST",
        kind === "start" ? { version: campaign.version } : undefined,
      );
      if (kind === "cancel") setStopping(true);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const labels: Record<string, string> = {
    draft: "Ready to start",
    queued: "Starting",
    discovering: "Finding businesses",
    researching: "Checking SEO fit",
    enriching: "Finding people",
    recommending: "Researching similar cities",
    completed: "Target reached",
    shortfall: "More cities needed",
    failed: "Search interrupted",
    cancelled: "Stopped",
    interrupted: "Interrupted",
  };
  return (
    <section className="search-run" aria-label={campaign.plan.name}>
      <header>
        <span className="search-run-icon">
          <Target size={20} />
        </span>
        <div>
          <small>LEAD SEARCH</small>
          <h3>{campaign.plan.name}</h3>
        </div>
        <span className={"search-status " + campaign.status}>
          {labels[campaign.status] || campaign.status}
        </span>
      </header>
      <div className="search-target">
        <strong>
          {found}
          <span> / {target}</span>
        </strong>
        <span>verified people</span>
        {campaign.status === "completed" && <Check size={20} />}
      </div>
      <progress value={found} max={target} aria-label="Verified people found" />
      <p className="search-location">
        <MapPin size={14} />
        {locations
          .map((item) => [item.city, item.state].filter(Boolean).join(", "))
          .filter(Boolean)
          .join(" · ") || "Supplied company websites"}
      </p>
      <p>{campaign.message}</p>
      {running && (
        <Spinner
          label={
            stopping
              ? "Stopping after the current provider request…"
              : labels[campaign.status]
          }
        />
      )}
      {campaign.status === "draft" && (
        <p className="muted">
          Up to 70 businesses per location. The search continues through these
          locations until {target} new people are found or the locations are
          exhausted.
        </p>
      )}
      {!!campaign.locations?.length && (
        <details className="search-breakdown">
          <summary>
            Results by location · {campaign.progress.discovered} businesses
            found
          </summary>
          <ul>
            {campaign.locations.map((item, i) => (
              <li key={i}>
                <span>
                  {item.city || "Websites"}
                  {item.state ? ", " + item.state : ""}
                </span>
                <strong>{item.leads} leads</strong>
                <small>
                  {item.processed}/{item.discovered} businesses processed
                </small>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!!campaign.recommendations?.length && (
        <div className="city-recommendations">
          <h4>Similar cities to try next</h4>
          <p>
            {campaign.shortfall} more leads are needed. These cities are
            recommendations, not additional searches already started.
          </p>
          {campaign.recommendations.map((item) => (
            <article key={item.city + item.state}>
              <strong>
                {item.city}, {item.state}
              </strong>
              <p>{item.reason}</p>
              {item.evidence.slice(0, 2).map((e) => (
                <ExternalLink key={e.url} url={e.url}>
                  {e.title}
                </ExternalLink>
              ))}
            </article>
          ))}
          <button
            className="btn-secondary small"
            onClick={() =>
              suggest(
                `Find ${campaign.shortfall} more leads for ${campaign.plan.niche}, continuing the search "${campaign.plan.name}" with the same SEO criteria and exclusions, in these cities: ${campaign.recommendations!.map((item) => item.city + ", " + item.state).join("; ")}.`,
              )
            }
          >
            Use these cities in my next request <ArrowRight size={14} />
          </button>
        </div>
      )}
      {!!campaign.warnings.length && (
        <details className="search-breakdown">
          <summary>Research limitations ({campaign.warnings.length})</summary>
          {campaign.warnings.map((warning, i) => (
            <p key={i}>{warning}</p>
          ))}
        </details>
      )}
      <small className="search-policy">
        Verified includes NeverBounce valid, catch-all and unknown. Exact email
        statuses remain visible in your lead database.
      </small>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      <footer>
        {campaign.status === "draft" && (
          <button
            className="btn-primary small"
            disabled={busy}
            onClick={() => void action("start")}
          >
            Find {target} leads <ArrowRight size={14} />
          </button>
        )}
        {running && (
          <button
            className="btn-secondary small"
            disabled={busy || stopping}
            onClick={() => void action("cancel")}
          >
            <Square size={12} />
            {stopping ? "Stop requested" : "Stop search"}
          </button>
        )}
        <button className="text-link" onClick={viewLeads}>
          View leads <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  );
}
