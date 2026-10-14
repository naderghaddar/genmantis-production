import { isActive, type RunStatus } from '../services/api';

export default function AgentRunProgress({ run, downloading, onDownload }: {
  run: RunStatus; downloading: boolean; onDownload: (kind: 'verified' | 'all') => void;
}) {
  const p = run.progress;
  return <section className="agent-run" aria-label="Lead search progress" aria-live="polite">
    <h2>{isActive(run) ? run.message : run.status === 'failed' ? 'Search failed' : 'Your results are ready'}</h2>
    <div className="progress-counts">
      <p>Businesses found: <strong>{p.businesses_scraped}</strong></p>
      <p>Eligible for enrichment: <strong>{p.businesses_eligible ?? p.businesses_scraped}</strong></p>
      <p>Businesses processed: <strong>{p.businesses_processed} / {p.businesses_scraped}</strong></p>
      <p>Verified selected contacts: <strong>{p.verified_emails}</strong></p>
      <p>Unverified selected contacts: <strong>{p.unverified_contacts ?? 0}</strong></p>
      <p>Filtered out: <strong>{p.businesses_filtered ?? 0}</strong></p>
    </div>
    {run.warnings?.map(warning => <p className="status" key={warning}>{warning}</p>)}
    {run.status === 'failed' && <p className="error" role="alert">{run.message}</p>}
    {run.status === 'completed' && run.downloads_ready && <>
      <div className="download-actions"><button className="download" disabled={downloading} onClick={() => onDownload('verified')}>Download Verified Leads</button>
        <button className="download" disabled={downloading} onClick={() => onDownload('all')}>Download All Results</button></div>
      <p className="status">The contact CSV includes one selected contact per domain, ordered by email status, with invalid emails excluded. All Results includes filtered businesses and source ranking evidence.</p>
    </>}
  </section>;
}
