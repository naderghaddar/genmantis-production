import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LeadScraper from './LeadScraper';
import { downloadCsv, getRunStatus, startRun } from '../services/api';

vi.mock('../services/api', async (importOriginal) => ({ ...await importOriginal<typeof import('../services/api')>(), startRun: vi.fn(), getRunStatus: vi.fn(), downloadCsv: vi.fn() }));
const running = {
  run_id: 'run123', apify_run_id: 'apify123', status: 'scraping' as const, message: 'Scraping businesses...',
  failure_reason: null, downloads_ready: false, created_at: '2026-10-14T12:00:00Z', completed_at: null,
  progress: { businesses_scraped: 0, businesses_processed: 0, domains_searched: 0, contacts_found: 0,
    verified_emails: 0, generic_emails_selected: 0, businesses_without_contact: 0, failed_enrichments: 0 },
};
const completed = { ...running, status: 'completed' as const, downloads_ready: true,
  progress: { ...running.progress, businesses_scraped: 2, businesses_processed: 2, verified_emails: 1 } };
function fill() {
  fireEvent.change(screen.getByLabelText('Niche'), { target: { value: 'Chiropractors' } });
  fireEvent.change(screen.getByLabelText('City'), { target: { value: 'Austin' } });
  fireEvent.change(screen.getByLabelText('State'), { target: { value: 'Texas' } });
}
async function begin() {
  fill();
  fireEvent.click(screen.getByRole('button', { name: /Find and Enrich Leads/ }));
  await act(async () => {});
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(startRun).mockResolvedValue(running); });
afterEach(() => { vi.useRealTimers(); });

describe('LeadScraper', () => {
  it('has exactly three required inputs and rejects whitespace', async () => {
    render(<LeadScraper />);
    expect(screen.getAllByRole('textbox')).toHaveLength(3);
    for (const field of screen.getAllByRole('textbox')) expect(field).toBeRequired();
    fill();
    fireEvent.change(screen.getByLabelText('Niche'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: /Find and Enrich Leads/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a niche');
    expect(startRun).not.toHaveBeenCalled();
  });
  it('polls to completion, prevents duplicates, and downloads', async () => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockResolvedValue(completed);
    render(<LeadScraper />);
    await begin();
    expect(screen.getByRole('button', { name: /Scraping businesses/ })).toBeDisabled();
    expect(startRun).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByText('Businesses scraped:')).toHaveTextContent('2');
    fireEvent.click(screen.getByRole('button', { name: 'Download Verified Leads' }));
    await act(async () => {});
    expect(downloadCsv).toHaveBeenCalledWith('run123', 'verified', expect.any(AbortSignal));
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getRunStatus).toHaveBeenCalledTimes(1);
  });
  it('handles a failed run and allows a new search', async () => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockResolvedValue({ ...running, status: 'failed', message: 'Scraping timed out. Please try again.' });
    render(<LeadScraper />);
    await begin();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByRole('alert')).toHaveTextContent('timed out');
    expect(screen.getByRole('button', { name: /Find and Enrich Leads/ })).toBeEnabled();
  });
  it('handles zero verified results and offers both exports', async () => {
    vi.mocked(startRun).mockResolvedValue({ ...completed, progress: { ...completed.progress, verified_emails: 0 } });
    render(<LeadScraper />);
    await begin();
    expect(screen.getByText('No selected business contacts were verified. All results are preserved.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download All Results' })).toBeInTheDocument();
  });
  it('resumes a status error on the same run', async () => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValueOnce(completed);
    render(<LeadScraper />);
    await begin();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByRole('alert')).toHaveTextContent('Connection lost');
    fireEvent.click(screen.getByRole('button', { name: 'Resume status check' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByText('Verified contacts:')).toHaveTextContent('1');
    expect(startRun).toHaveBeenCalledTimes(1);
  });
  it('cleans up pending polling on unmount', async () => {
    vi.useFakeTimers();
    const view = render(<LeadScraper />);
    await begin();
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getRunStatus).not.toHaveBeenCalled();
  });
  it('shows startup errors', async () => {
    vi.mocked(startRun).mockRejectedValue(new Error('Set APIFY_API_TOKEN in backend/.env'));
    render(<LeadScraper />);
    await begin();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('APIFY_API_TOKEN'));
    expect(screen.getByRole('button', { name: /Find and Enrich Leads/ })).toBeEnabled();
  });

  it('displays real backend stage and counts and downloads all results', async () => {
    vi.useFakeTimers();
    vi.mocked(getRunStatus).mockResolvedValueOnce({ ...running, status: 'verifying', message: 'Verifying emails...',
      progress: { ...running.progress, businesses_scraped: 20, businesses_processed: 7, verified_emails: 4 } }).mockResolvedValueOnce(completed);
    render(<LeadScraper />);
    await begin();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByText('Businesses processed:')).toHaveTextContent('7 / 20');
    expect(screen.getByText('Verified contacts:')).toHaveTextContent('4');
    expect(screen.getByRole('button', { name: /Verifying emails/ })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    fireEvent.click(screen.getByRole('button', { name: 'Download All Results' }));
    await act(async () => {});
    expect(downloadCsv).toHaveBeenCalledWith('run123', 'all', expect.any(AbortSignal));
  });

  it('reuses the request key after a lost start response', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValueOnce(running);
    render(<LeadScraper />);
    await begin();
    expect(screen.getByRole('alert')).toHaveTextContent('Connection lost');
    fireEvent.click(screen.getByRole('button', { name: /Find and Enrich Leads/ }));
    await act(async () => {});
    expect(vi.mocked(startRun).mock.calls[0][2]).toBe(vi.mocked(startRun).mock.calls[1][2]);
  });
});
