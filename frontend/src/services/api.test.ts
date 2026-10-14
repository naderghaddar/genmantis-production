import { afterEach, expect, it, vi } from 'vitest';
import { downloadCsv, getRunStatus, startRun } from './api';

afterEach(() => { vi.unstubAllGlobals(); });

it('posts one request with a stable idempotency key', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: 'run123' }), { status: 202 }));
  vi.stubGlobal('fetch', fetchMock);
  const input = { niche: 'Chiropractors', city: 'Austin', state: 'Texas' };
  const signal = new AbortController().signal;
  await startRun(input, signal, 'request123');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith('/api/runs', expect.objectContaining({
    method: 'POST', body: JSON.stringify(input), headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'request123' }, signal,
  }));
});

it('checks status without starting a new job', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'verifying' })));
  vi.stubGlobal('fetch', fetchMock);
  await getRunStatus('run123', new AbortController().signal);
  expect(fetchMock).toHaveBeenCalledWith('/api/runs/run123', expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

it('reports safe backend errors without retrying', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Missing Hunter key' }), { status: 503 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(startRun({ niche: 'x', city: 'y', state: 'z' }, new AbortController().signal, 'request123')).rejects.toThrow('Missing Hunter key');
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('downloads the selected export using the backend filename', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('header\r\n', { headers: { 'Content-Disposition': 'attachment; filename="clinic_all_results.csv"' } }));
  vi.stubGlobal('fetch', fetchMock);
  const createObjectURL = vi.fn().mockReturnValue('blob:test');
  const revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe('clinic_all_results.csv');
  });
  await downloadCsv('run123', 'all', new AbortController().signal);
  expect(fetchMock).toHaveBeenCalledWith('/api/runs/run123/download?type=all', expect.anything());
  expect(click).toHaveBeenCalledOnce();
  expect(createObjectURL).toHaveBeenCalledOnce();
});
