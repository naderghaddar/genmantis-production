import { useState } from "react";
import { Download, Terminal } from "lucide-react";
import { active, type Campaign } from "../../services/workspaceApi";

export default function SearchDebugLog({ campaign }: { campaign: Campaign }) {
  const [query, setQuery] = useState("");
  const [issuesOnly, setIssuesOnly] = useState(false);
  const entries = campaign.debug_log || [];
  const term = query.trim().toLowerCase();
  const filtered = entries.filter((entry) =>
    (!issuesOnly || entry.level === "warning" || entry.level === "error") &&
    (!term || `${entry.domain || ""} ${entry.message} ${entry.event} ${JSON.stringify(entry.details)}`.toLowerCase().includes(term)),
  ).slice().reverse();
  const total = campaign.diagnostics?.sequence || entries.length;

  function download() {
    const blob = new Blob([JSON.stringify({ campaign_id: campaign.id, status: campaign.status,
      progress: campaign.progress, total_events: total, debug_log: entries }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `search-${campaign.id}-debug.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="search-debug" aria-label="Search debug log">
    <div className="debug-heading"><h4><Terminal size={16} /> Flow debug log</h4>
      <span>{active(campaign) ? "Updates every 4 seconds" : "Saved log"}</span>
      <button type="button" className="btn-secondary small" disabled={!entries.length} onClick={download}><Download size={14} /> Download log</button>
    </div>
    <div className="debug-filters">
      <input aria-label="Filter debug log" placeholder="Filter by domain, result, or step..." value={query} onChange={(event) => setQuery(event.target.value)} />
      <label><input type="checkbox" checked={issuesOnly} onChange={(event) => setIssuesOnly(event.target.checked)} /> Warnings and errors only</label>
    </div>
    <p className="debug-caption">Newest first. {filtered.length} matching entries. {total > entries.length ? `Showing the latest ${entries.length} of ${total} events; older entries were trimmed.` : `${entries.length} events recorded.`}</p>
    <div className="debug-entries" tabIndex={0} aria-label="Debug entries">
      {filtered.map((entry) => <div key={entry.id} className={`debug-entry debug-${entry.level}`}>
        <div className="debug-entry-meta"><time dateTime={entry.at} title={new Date(entry.at).toLocaleString()}>{new Date(entry.at).toLocaleTimeString()}</time><span className="debug-level">{entry.level}</span><code>{entry.event}</code></div>
        {entry.domain && <strong className="debug-domain">{entry.domain}</strong>}
        <p>{entry.message}</p>
        {!!Object.keys(entry.details || {}).length && <details><summary>Details</summary><pre>{JSON.stringify(entry.details, null, 2)}</pre></details>}
      </div>)}
      {!filtered.length && <p className="debug-empty">{entries.length ? "No events match this filter." : active(campaign) ? "Waiting for debug events. Detailed logging is available for searches started after the backend update." : "No detailed log was recorded for this search. New searches will record each step."}</p>}
    </div>
  </section>;
}
