export type SessionStatus =
  | 'unknown'
  | 'authenticated'
  | 'unauthenticated'
  | 'password_change_required';

export type SessionState = {
  status: SessionStatus;
  currentAdmin?: API.AdminProfile;
};

export const UNKNOWN_SESSION: SessionState = { status: 'unknown' };

let unauthorizedHandler: (() => void) | undefined;

export function registerUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler;
}

export function clearUnauthorizedSession(): void {
  unauthorizedHandler?.();
}

export async function loadSession(
  current: SessionState,
  fetchCurrentAdmin: () => Promise<API.AdminProfile>,
): Promise<SessionState> {
  if (current.status !== 'unknown') {
    return current;
  }
  try {
    const currentAdmin = await fetchCurrentAdmin();
    return {
      status: currentAdmin.firstLoginRequired
        ? 'password_change_required'
        : 'authenticated',
      currentAdmin,
    };
  } catch (error) {
    const apiError = toApiClientError(error);
    if (apiError.status === 401) {
      return { status: 'unauthenticated' };
    }
    throw apiError;
  }
}

export function loginRedirect(location: {
  pathname: string;
  search: string;
  hash: string;
}): string {
  const returnUrl = `${location.pathname}${location.search}${location.hash}`;
  return `/login?redirect=${encodeURIComponent(returnUrl)}`;
}

import { toApiClientError } from '@/features/api/errors';
