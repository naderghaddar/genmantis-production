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
  // Old completed searches had no cap; old drafts use the new default on start.
  const companyLimit = campaign.plan.max_leads_per_company === undefined
    ? (campaign.status === "draft" ? 1 : null)
    : campaign.plan.max_leads_per_company;
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
    shortfall: "Target not yet reached",
    failed: "Search interrupted",
    cancelled: "Stopped",
    interrupted: "Interrupted",
  };
  const stopReasons: Record<string, string> = {
    city_depth_budget_reached: "The configured search depth was reached. You can request a larger pass budget or select more cities.",
    approved_locations_exhausted: "No further results were available in the selected cities.",
    hunter_quota_exhausted: "Hunter credits or usage allowance are exhausted.",
    neverbounce_quota_exhausted: "NeverBounce credits or usage allowance are exhausted.",
    hunter_authentication_error: "Hunter authentication needs attention.",
    neverbounce_authentication_error: "NeverBounce authentication needs attention.",
    hunter_rate_limit_cooldown: "Hunter requires a cooldown before more requests.",
    neverbounce_rate_limit_cooldown: "NeverBounce requires a cooldown before more requests.",
    contact_provider_unavailable: "Contact discovery failed repeatedly. Saved leads are retained.",
    email_provider_unavailable: "Email checks failed repeatedly. Failed checks did not count as leads.",
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
      <p className="muted">
        {companyLimit === null
          ? "No per-company lead limit."
          : `At most ${companyLimit} ${companyLimit === 1 ? "lead" : "leads"} per company, including saved leads.`}
        {" "}Companies are matched by website domain. Duplicate emails are always skipped.
      </p>
      {campaign.stop_reason && stopReasons[campaign.stop_reason] && (
        <p className="muted">{stopReasons[campaign.stop_reason]}</p>
      )}
      {running && (
        <Spinner
          label={
            stopping
              ? "Stopping after the current provider request…"
              : labels[campaign.status]
          }
        />
      )}
      {(campaign.status === "draft" || running) && (
        <p className="muted">
          Starts with 100 businesses per city, with up to {campaign.plan.max_city_rounds ?? 1} passes
          in these cities only. Stops at {target} new people or when the available
          results or search budget are exhausted.
        </p>
      )}
      {!!campaign.progress.review && (
        <p className="muted">{campaign.progress.review} businesses had insufficient qualification or website identity evidence and did not count toward the target.</p>
      )}
      {!!campaign.diagnostics?.counts.company_niche_excluded && (
        <p className="muted">{campaign.diagnostics.counts.company_niche_excluded} businesses did not match the requested niche and were excluded.</p>
      )}
      {!!campaign.diagnostics?.counts.company_location_excluded && (
        <p className="muted">{campaign.diagnostics.counts.company_location_excluded} businesses were listed outside the requested city and were excluded.</p>
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
                  {(item.round ?? 1) > 1 ? ` · Pass ${item.round}` : ""}
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
                `Find ${campaign.shortfall} more leads for ${campaign.plan.niche}, continuing the search "${campaign.plan.name}" with the same SEO criteria and exclusions, ${companyLimit === null ? "with no per-company lead limit" : `with at most ${companyLimit} leads per company including saved leads`}, excluding existing emails, in these cities: ${campaign.recommendations!.map((item) => item.city + ", " + item.state).join("; ")}.`,
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
        {campaign.plan.email_policy === "valid_only"
          ? "Only NeverBounce valid emails count toward this target."
          : "Verified includes NeverBounce valid, catch-all and unknown. Catch-all and unknown do not confirm deliverability."}
        {" "}Exact email statuses remain visible in your lead database.
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
