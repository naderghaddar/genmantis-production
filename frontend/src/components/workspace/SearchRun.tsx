import { useState } from "react";
import { ArrowRight, Play, Square } from "lucide-react";
import { active, api, type Campaign } from "../../services/workspaceApi";
import { Badge } from "./Shared";
import SearchDebugLog from "./SearchDebugLog";

export default function SearchRun({ campaign, refresh, viewLeads }: {
  campaign: Campaign;
  refresh: () => Promise<void>;
  viewLeads: () => void;
  suggest?: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const running = active(campaign);
  const current = campaign.workflow === "sequential-v1";
  const p = campaign.progress;
  async function action(kind: "start" | "cancel") {
    setBusy(true); setError("");
    try {
      const result = await api<{ requested?: boolean }>(`/campaigns/${campaign.id}/${kind}`, "POST", kind === "start" ? { version: campaign.version } : undefined);
      if (kind === "cancel" && result.requested) setStopping(true);
      await refresh();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <article className="data-card simple-run">
    <div className="run-heading"><div><h3>{campaign.plan.name || campaign.plan.niche}</h3><small>{new Date(campaign.created_at).toLocaleString()}</small></div><Badge value={campaign.status}>{campaign.status.replaceAll("_", " ")}</Badge></div>
    <p className="run-message" role={running ? "status" : undefined}>{current ? campaign.message : "Previous search. Saved leads remain available."}</p>
    {current && <>
      <div className="run-counts">
        <span><strong>{p.cities_completed || 0} / {p.cities_total || 0}</strong>Cities scraped</span>
        <span><strong>{p.scraped || 0}</strong>Businesses scraped</span>
        <span><strong>{p.duplicates || 0}</strong>Duplicate domains removed</span>
        <span><strong>{p.processed} / {p.discovered}</strong>Domains processed</span>
        <span><strong>{p.checked || 0}</strong>Emails checked</span>
        <span><strong>{p.verified}</strong>Leads saved</span>
      </div>
      {running && <progress aria-label={campaign.status === "discovering" ? "Cities scraped" : "Domains processed"} value={campaign.status === "discovering" ? p.cities_completed || 0 : p.processed} max={Math.max(1, campaign.status === "discovering" ? p.cities_total || 0 : p.discovered)} />}
      <p className="muted">{p.reused} existing emails skipped ? {p.rejected || 0} rejected emails ? {p.verification_errors || 0} verification errors ? {p.excluded} rank exclusions ? {p.no_contact || 0} results without a website or eligible contact</p>
      {!!campaign.locations?.length && <details><summary>City results</summary><ul>{campaign.locations.map((city, i) => <li key={i}>{city.city}, {city.state}: {city.discovered} businesses ? {city.status}</li>)}</ul></details>}
      {campaign.stop_reason && campaign.status === "failed" && <p className="error-banner">{campaign.stop_reason.replaceAll("_", " ")}</p>}
      {campaign.warnings.map((warning, i) => <p className="detail-warning" key={i}>{warning}</p>)}
      <SearchDebugLog campaign={campaign} />
    </>}
    <div className="search-buttons">
      {current && campaign.status === "draft" && <button className="btn-primary small" disabled={busy} onClick={() => void action("start")}><Play size={14} /> Start search</button>}
      {running && <button className="btn-secondary small" disabled={busy || stopping} onClick={() => void action("cancel")}><Square size={14} />{stopping ? "Stopping?" : "Stop search"}</button>}
      <button className="btn-secondary small" onClick={viewLeads}>View {p.verified} saved leads <ArrowRight size={14} /></button>
    </div>
    {error && <p className="error-banner" role="alert">{error}</p>}
  </article>;
}
