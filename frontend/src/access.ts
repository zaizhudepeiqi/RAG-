import type { SessionState } from '@/features/auth/session';

export default function access(initialState?: { session: SessionState }) {
  const status = initialState?.session.status ?? 'unknown';
  return {
    authenticated: status === 'authenticated',
    passwordChangeAllowed:
      status === 'authenticated' || status === 'password_change_required',
  };
}
