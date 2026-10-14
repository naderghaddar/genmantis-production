import { useEffect, useRef, useState, type FormEvent } from 'react';
import { downloadCsv, getRunStatus, startRun, isActive, type ScrapeInput, type RunStatus } from '../services/api';

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.';

export default function LeadScraper() {
  const [input, setInput] = useState<ScrapeInput>({ niche: '', city: '', state: '' });
  const [run, setRun] = useState<RunStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const [pollPaused, setPollPaused] = useState(false);
  const action = useRef<AbortController | null>(null);
  const busy = starting || isActive(run);
  const requestKey = useRef<{ fingerprint: string; key: string } | null>(null);

  useEffect(() => () => action.current?.abort(), []);

  useEffect(() => {
    if (!isActive(run) || pollPaused) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getRunStatus(run!.run_id, controller.signal);
        if (controller.signal.aborted) return;
        setRun(next);
        if (isActive(next)) timer = setTimeout(poll, 3000);
      } catch (err) {
        if (!controller.signal.aborted) { setError(errorMessage(err)); setPollPaused(true); }
      }
    }
    timer = setTimeout(poll, 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [run?.run_id, run?.status, pollPaused]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || action.current) return;
    const trimmed = { niche: input.niche.trim(), city: input.city.trim(), state: input.state.trim() };
    if (Object.values(trimmed).some(value => !value)) { setError('Enter a niche, city, and state.'); return; }
    const fingerprint = JSON.stringify(trimmed);
    if (!requestKey.current || requestKey.current.fingerprint !== fingerprint || run?.status === 'completed' || run?.status === 'failed') {
      requestKey.current = { fingerprint, key: crypto.randomUUID() };
    }
    const controller = new AbortController();
    action.current = controller;
    setStarting(true); setError(''); setRun(null); setPollPaused(false);
    try {
      const next = await startRun(trimmed, controller.signal, requestKey.current.key);
      if (!controller.signal.aborted) setRun(next);
    } catch (err) {
      if (!controller.signal.aborted) setError(errorMessage(err));
    } finally {
      if (!controller.signal.aborted) setStarting(false);
      action.current = null;
    }
  }

  async function download(type: 'verified' | 'all') {
    if (!run || action.current) return;
    const controller = new AbortController();
    action.current = controller;
    setDownloading(true); setError('');
    try { await downloadCsv(run.run_id, type, controller.signal); }
    catch (err) { if (!controller.signal.aborted) setError(errorMessage(err)); }
    finally { if (!controller.signal.aborted) setDownloading(false); action.current = null; }
  }

  return <section className="scraper">
    <div className="intro"><p className="eyebrow"><span /> LOCAL BUSINESS DISCOVERY</p>
      <h1>Lead Scraper</h1>
      <p className="description">Find your next business connection.<br />Find decision-makers, verify emails, and export your leads.</p>
    </div>
    <div className="card">
      <div className="card-heading"><span className="search-icon" aria-hidden="true">&#9906;</span><div><h2>Start your search</h2><p>A niche. A location. Your next opportunity.</p></div></div>
      <form onSubmit={submit}>
        <fieldset disabled={busy || downloading}>
          <label htmlFor="niche">Niche<input id="niche" name="niche" placeholder="e.g., Chiropractors" required maxLength={200} value={input.niche} onChange={e => setInput({ ...input, niche: e.target.value })} /></label>
          <div className="location-fields">
            <label htmlFor="city">City<input id="city" name="city" placeholder="e.g., Austin" required maxLength={200} value={input.city} onChange={e => setInput({ ...input, city: e.target.value })} /></label>
            <label htmlFor="state">State<input id="state" name="state" placeholder="e.g., Texas or TX" required maxLength={200} value={input.state} onChange={e => setInput({ ...input, state: e.target.value })} /></label>
          </div>
        </fieldset>
        <button className="primary" type="submit" disabled={busy || downloading}>{busy ? <><span className="spinner" />{run?.message ?? 'Starting your search...'}</> : <>Find and Enrich Leads <span aria-hidden="true">&#8599;</span></>}</button>
      </form>
      <div className="feedback" aria-live="polite" aria-atomic="true">
        {busy && !pollPaused && <p className="status">{starting ? 'Starting your search...' : run?.message}</p>}
        {run?.status === 'failed' && <p className="error" role="alert">{run.message}</p>}
        {run && run.status !== 'pending' && run.status !== 'failed' && <div className="progress-counts">
          <p>Businesses {run.status === 'completed' ? 'scraped' : 'found'}: <strong>{run.progress.businesses_scraped}</strong></p>
          {run.status !== 'completed' && <p>Businesses processed: <strong>{run.progress.businesses_processed} / {run.progress.businesses_scraped}</strong></p>}
          <p>Verified contacts: <strong>{run.progress.verified_emails}</strong></p>
          {run.status === 'completed' && <>
            <p>Generic contacts: <strong>{run.progress.generic_emails_selected}</strong></p>
            <p>Businesses without verified email: <strong>{run.progress.businesses_scraped - run.progress.verified_emails}</strong></p>
            {run.progress.failed_enrichments > 0 && <p className="status">Some provider requests failed. See All Results for each business's outcome.</p>}
          </>}
        </div>}
        {run?.status === 'completed' && <div className="result">
          <span className="success-mark" aria-hidden="true">&#10003;</span>
          <div><strong>Enrichment complete</strong><p>{run.progress.businesses_scraped === 0 ? 'No businesses found. Try another niche or location.' : run.progress.verified_emails === 0 ? 'No selected business contacts were verified. All results are preserved.' : 'Your leads are ready to export.'}</p></div>
          {run.downloads_ready && <div className="download-actions">
            <button className="download" type="button" disabled={downloading} onClick={() => download('verified')}>Download Verified Leads</button>
            <button className="download" type="button" disabled={downloading} onClick={() => download('all')}>Download All Results</button>
          </div>}
          {run.downloads_ready && <p className="status">One selected contact per domain: decision-makers first, generic email as fallback. Invalid emails are excluded. A blank email_status means verification was unavailable.</p>}
          {downloading && <p className="status">Downloading...</p>}
        </div>}
        {error && <p className="error" role="alert">{error}</p>}
        {pollPaused && <button className="retry" type="button" onClick={() => { setError(''); setPollPaused(false); }}>Resume status check</button>}
      </div>
      <p className="card-note"><span aria-hidden="true">&#8595;</span> Verified emails and business details, ready to export.</p>
    </div>
    <p className="below-card">Apify business data / Hunter contacts / NeverBounce verification</p>
  </section>;
}
