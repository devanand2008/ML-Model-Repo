// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import AuthGate from '../components/AuthGate';

const session = vi.hoisted(() => vi.fn());
vi.mock('../services/api', () => ({ session, setCredentials: vi.fn(), BASE_URL: '' }));
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.clearAllMocks(); });

it('public admin opens controls immediately without credential fields or a login request', () => {
  vi.stubEnv('VITE_PUBLIC_ADMIN', 'true');
  render(<MemoryRouter><AuthGate><h1>Admin controls</h1></AuthGate></MemoryRouter>);
  expect(screen.getByRole('heading', { name: 'Admin controls' })).toBeTruthy();
  expect(screen.queryByLabelText('Username')).toBeNull();
  expect(screen.queryByLabelText('Password')).toBeNull();
  expect(session).not.toHaveBeenCalled();
});

it('the laptop build retains its existing administrator sign-in', async () => {
  vi.stubEnv('VITE_PUBLIC_ADMIN', 'false');
  session.mockResolvedValue({ ok: false, status: 401 });
  render(<MemoryRouter><AuthGate><h1>Admin controls</h1></AuthGate></MemoryRouter>);
  expect(await screen.findByLabelText('Username')).toBeTruthy();
  expect(screen.getByLabelText('Password')).toBeTruthy();
  expect(screen.queryByText('Admin controls')).toBeNull();
});
