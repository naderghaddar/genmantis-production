import type { SearchPlan } from '../services/agentApi';

export default function SearchConfirmation({ plan, busy, onConfirm, onEdit }: {
  plan: SearchPlan; busy: boolean; onConfirm: () => void; onEdit: () => void;
}) {
  const min = plan.min_google_maps_rank, max = plan.max_google_maps_rank;
  const rank = min && max ? `Positions ${min} to ${max}` : min ? `Position ${min} or worse` : max ? `Top ${max}` : 'No ranking filter';
  return <section className="confirmation" aria-label="Search plan">
    <h2>Your search plan</h2>
    <dl><div><dt>Business type</dt><dd>{plan.niche}</dd></div>
      <div><dt>Location</dt><dd>{plan.city}, {plan.state}</dd></div>
      <div><dt>Google Maps position</dt><dd>{rank}</dd></div>
      <div><dt>Maximum businesses to enrich</dt><dd>{plan.max_leads}</dd></div></dl>
    <p>The source search collects up to 30 places. Rankings are specific to the search query and map area; missing rankings and ads cannot match a ranking filter.</p>
    <p>Starting this search uses your scraping and enrichment API credits.</p>
    <div className="confirmation-actions"><button className="primary" disabled={busy} onClick={onConfirm}>Start Lead Search</button>
      <button className="retry" disabled={busy} onClick={onEdit}>Edit Search</button></div>
  </section>;
}
