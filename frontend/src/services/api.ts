export interface ScrapeInput { niche: string; city: string; state: string }
export type RunStage = 'pending' | 'scraping' | 'enriching' | 'verifying' | 'exporting' | 'completed' | 'failed';
export interface RunProgress {
  businesses_scraped: number;
  businesses_processed: number;
  domains_searched: number;
  contacts_found: number;
  verified_emails: number;
  generic_emails_selected: number;
  businesses_without_contact: number;
  failed_enrichments: number;
  businesses_eligible?: number;
  businesses_filtered?: number;
  unverified_contacts?: number;
}
export interface RunStatus {
  run_id: string;
  apify_run_id: string | null;
  status: RunStage;
  progress: RunProgress;
  message: string;
  failure_reason: string | null;
  downloads_ready: boolean;
  created_at: string;
  completed_at: string | null;
  warnings?: string[];
}
export const isActive = (run: RunStatus | null) => !!run && run.status !== 'completed' && run.status !== 'failed';

export async function checkResponse(response: Response): Promise<Response> {
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail :
      response.status === 422 ? 'Enter a valid niche, city, and state (up to 200 characters each).' :
      `Request failed (${response.status}). Please try again.`);
  }
  return response;
}

export async function startRun(input: ScrapeInput, signal: AbortSignal, requestKey: string): Promise<RunStatus> {
  const response = await fetch('/api/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': requestKey }, body: JSON.stringify(input), signal,
  });
  return (await checkResponse(response)).json();
}

export async function getRunStatus(runId: string, signal: AbortSignal): Promise<RunStatus> {
  return (await checkResponse(await fetch(`/api/runs/${encodeURIComponent(runId)}`, { signal }))).json();
}

export async function downloadCsv(runId: string, type: 'verified' | 'all', signal: AbortSignal): Promise<void> {
  const response = await checkResponse(await fetch(`/api/runs/${encodeURIComponent(runId)}/download?type=${type}`, { signal }));
  const blob = await response.blob();
  const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? 'genmantis_leads.csv';
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
