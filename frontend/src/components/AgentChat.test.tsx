import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AgentChat from './AgentChat';
import { confirmPlan, createConversation, editPlan, getConversation, sendAgentMessage, type Conversation } from '../services/agentApi';
import { downloadCsv, type RunStatus } from '../services/api';

vi.mock('../services/agentApi', () => ({ confirmPlan: vi.fn(), createConversation: vi.fn(), editPlan: vi.fn(), getConversation: vi.fn(), sendAgentMessage: vi.fn() }));
vi.mock('../services/api', async (importOriginal) => ({ ...await importOriginal<typeof import('../services/api')>(), downloadCsv: vi.fn() }));

const initial: Conversation = {
  id: 'conversation1', messages: [{ id: 'welcome', role: 'assistant', content: 'Tell me what kind of businesses you want to reach.' }],
  plan: { id: 'plan1', version: 1, niche: null, city: null, state: null, country: null,
    business_size_preference: null, min_google_maps_rank: null, max_google_maps_rank: null,
    max_leads: 30, additional_preferences: [], unsupported_preferences: [], limitations: [], status: 'collecting_requirements' },
  confirmation_required: false, run: null, usage: { input_tokens: 0, output_tokens: 0, requests: 0 },
};
const planned: Conversation = { ...initial, confirmation_required: true,
  plan: { ...initial.plan, version: 2, niche: 'Chiropractors', city: 'Austin', state: 'Texas', min_google_maps_rank: 21, status: 'ready_for_confirmation' },
};
const running: RunStatus = {
  run_id: 'run1', apify_run_id: 'apify1', status: 'scraping', message: 'Scraping businesses...', failure_reason: null,
  downloads_ready: false, created_at: '2026-10-14T12:00:00Z', completed_at: null,
  progress: { businesses_scraped: 0, businesses_processed: 0, domains_searched: 0, contacts_found: 0, verified_emails: 0,
    generic_emails_selected: 0, businesses_without_contact: 0, failed_enrichments: 0 },
};

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); vi.mocked(createConversation).mockResolvedValue(initial); });
afterEach(() => vi.useRealTimers());

async function openReady() {
  vi.mocked(createConversation).mockResolvedValue(planned);
  render(<AgentChat />);
  await act(async () => {});
}

it('starts a conversation and sends natural language without starting a paid search', async () => {
  render(<AgentChat />);
  expect(await screen.findByText(initial.messages[0].content)).toBeInTheDocument();
  vi.mocked(sendAgentMessage).mockResolvedValue(planned);
  fireEvent.change(screen.getByLabelText('Message GenMantis'), { target: { value: 'Find chiropractors in Austin outside the top 20' } });
  fireEvent.keyDown(screen.getByLabelText('Message GenMantis'), { key: 'Enter' });
  expect(await screen.findByRole('button', { name: 'Start Lead Search' })).toBeInTheDocument();
  expect(screen.getByText('Position 21 or worse')).toBeInTheDocument();
  expect(screen.getByText('Austin, Texas')).toBeInTheDocument();
  expect(confirmPlan).not.toHaveBeenCalled();
  expect(sendAgentMessage).toHaveBeenCalledTimes(1);
});

it('confirms an exact plan only once on repeated clicks', async () => {
  await openReady();
  vi.mocked(confirmPlan).mockResolvedValue({ ...planned, confirmation_required: false, run: running });
  const button = screen.getByRole('button', { name: 'Start Lead Search' });
  fireEvent.click(button);
  fireEvent.click(button);
  await act(async () => {});
  expect(confirmPlan).toHaveBeenCalledTimes(1);
  expect(confirmPlan).toHaveBeenCalledWith(planned.plan, expect.any(AbortSignal));
  expect(screen.getByRole('heading', { name: 'Scraping businesses...' })).toBeInTheDocument();
});

it('edits a plan before starting and returns focus to conversation', async () => {
  await openReady();
  vi.mocked(editPlan).mockResolvedValue({ ...planned, confirmation_required: false });
  fireEvent.click(screen.getByRole('button', { name: 'Edit Search' }));
  await act(async () => {});
  expect(editPlan).toHaveBeenCalledWith(planned.plan, expect.any(AbortSignal));
  expect(confirmPlan).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Message GenMantis')).toHaveFocus();
});

it('polls real progress and offers both downloads on completion', async () => {
  vi.useFakeTimers();
  vi.mocked(createConversation).mockResolvedValue({ ...planned, confirmation_required: false, run: running });
  const complete = { ...running, status: 'completed' as const, downloads_ready: true,
    progress: { ...running.progress, businesses_scraped: 30, businesses_processed: 30, businesses_eligible: 25,
      businesses_filtered: 5, verified_emails: 20, unverified_contacts: 3 } };
  vi.mocked(getConversation).mockResolvedValue({ ...planned, confirmation_required: false, run: complete });
  render(<AgentChat />);
  await act(async () => {});
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(screen.getByText('Verified selected contacts:')).toHaveTextContent('20');
  expect(screen.getByText('Filtered out:')).toHaveTextContent('5');
  fireEvent.click(screen.getByRole('button', { name: 'Download Verified Leads' }));
  await act(async () => {});
  expect(downloadCsv).toHaveBeenLastCalledWith('run1', 'verified', expect.any(AbortSignal));
  fireEvent.click(screen.getByRole('button', { name: 'Download All Results' }));
  await act(async () => {});
  expect(downloadCsv).toHaveBeenLastCalledWith('run1', 'all', expect.any(AbortSignal));
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(getConversation).toHaveBeenCalledTimes(1);
});

it('shows failed runs without claiming success', async () => {
  vi.mocked(createConversation).mockResolvedValue({ ...planned, confirmation_required: false,
    run: { ...running, status: 'failed', message: 'Scraping timed out. Check Apify Console.' } });
  render(<AgentChat />);
  expect(await screen.findByRole('alert')).toHaveTextContent('timed out');
  expect(screen.queryByRole('button', { name: 'Download Verified Leads' })).not.toBeInTheDocument();
});

it('retains failed messages and reuses their request key on retry', async () => {
  render(<AgentChat />);
  await screen.findByText(initial.messages[0].content);
  vi.mocked(sendAgentMessage).mockRejectedValueOnce(new Error('OpenAI unavailable')).mockResolvedValueOnce(planned);
  fireEvent.change(screen.getByLabelText('Message GenMantis'), { target: { value: 'Find chiropractors' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('OpenAI unavailable');
  expect(screen.getByLabelText('Message GenMantis')).toHaveValue('Find chiropractors');
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(sendAgentMessage).toHaveBeenCalledTimes(2));
  expect(vi.mocked(sendAgentMessage).mock.calls[0][2]).toBe(vi.mocked(sendAgentMessage).mock.calls[1][2]);
});

it('restores persisted conversation rather than creating a new one', async () => {
  localStorage.setItem('genmantis_conversation', 'conversation1');
  vi.mocked(getConversation).mockResolvedValue(initial);
  render(<AgentChat />);
  await screen.findByText(initial.messages[0].content);
  expect(getConversation).toHaveBeenCalledWith('conversation1', expect.any(AbortSignal));
  expect(createConversation).not.toHaveBeenCalled();
});

it('cleans up polling when unmounted', async () => {
  vi.useFakeTimers();
  vi.mocked(createConversation).mockResolvedValue({ ...planned, confirmation_required: false, run: running });
  const view = render(<AgentChat />);
  await act(async () => {});
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(getConversation).not.toHaveBeenCalled();
});
