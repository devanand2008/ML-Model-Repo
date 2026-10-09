// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import HostingStatus from '../components/HostingStatus';

const fetcher = vi.fn();
beforeEach(() => {
  vi.stubEnv('VITE_HOSTING_MODE', 'free-hybrid');
  vi.stubEnv('VITE_PUBLIC_ADMIN', 'true');
  vi.stubGlobal('fetch', fetcher);
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); fetcher.mockReset(); });
const status = (online: boolean) => ({ ok: true, json: async () => ({ ml_online: online }) });

it('automatically recovers an unavailable connection without refreshing the page', async () => {
  vi.useFakeTimers();
  fetcher.mockResolvedValueOnce(status(false)).mockResolvedValueOnce(status(true));
  await act(async () => { render(<HostingStatus />); });
  expect(screen.getByRole('status').textContent).toContain('Retrying automatically');
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(screen.getByRole('status').textContent).toContain('ML connected');
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[0][1].cache).toBe('no-store');
});

it('offers an immediate retry after a network check fails', async () => {
  fetcher.mockRejectedValueOnce(new TypeError('Network unavailable')).mockResolvedValueOnce(status(true));
  render(<HostingStatus />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry connection' }));
  await screen.findByText(/ML connected/);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('button', { name: 'Retry connection' })).toBeNull();
});

it('checks again when the tab becomes visible and aborts checks on unmount', async () => {
  fetcher.mockResolvedValueOnce(status(true)).mockImplementationOnce(() => new Promise(() => {}));
  const view = render(<HostingStatus />);
  await screen.findByText(/ML connected/);
  fireEvent(document, new Event('visibilitychange'));
  expect(fetcher).toHaveBeenCalledTimes(2);
  const signal = fetcher.mock.calls[1][1].signal;
  view.unmount();
  expect(signal.aborted).toBe(true);
});

it('does not check cloud hosting on the laptop build', () => {
  vi.stubEnv('VITE_HOSTING_MODE', 'local');
  render(<HostingStatus />);
  expect(screen.queryByRole('status')).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});
