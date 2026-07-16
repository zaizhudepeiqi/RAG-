import {
  loadSession,
  loginRedirect,
  UNKNOWN_SESSION,
} from '@/features/auth/session';

describe('administrator session', () => {
  it('loads authMe once when initial session state is unknown', async () => {
    const authMe = jest.fn().mockResolvedValue({
      id: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
      username: 'admin',
      firstLoginRequired: true,
    });

    const loaded = await loadSession(UNKNOWN_SESSION, authMe);
    const reused = await loadSession(loaded, authMe);

    expect(authMe).toHaveBeenCalledTimes(1);
    expect(loaded.status).toBe('password_change_required');
    expect(reused).toBe(loaded);
  });

  it('redirects unauthenticated users to login with an encoded full return URL', () => {
    expect(
      loginRedirect({
        pathname: '/tasks',
        search: '?status=running',
        hash: '#operation',
      }),
    ).toBe('/login?redirect=%2Ftasks%3Fstatus%3Drunning%23operation');
  });

  it('does not treat an unavailable auth service as an unauthenticated session', async () => {
    const authMe = jest.fn().mockRejectedValue({
      response: {
        status: 503,
        data: {
          code: 'DEPENDENCY_UNAVAILABLE',
          message: '认证服务暂时不可用',
          traceId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
        },
      },
    });

    await expect(loadSession(UNKNOWN_SESSION, authMe)).rejects.toMatchObject({
      status: 503,
      code: 'DEPENDENCY_UNAVAILABLE',
      message: '认证服务暂时不可用',
      traceId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
    });
  });
});
