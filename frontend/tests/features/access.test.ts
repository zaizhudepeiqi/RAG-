import access from '@/access';

describe('route access', () => {
  it('allows password-change-required administrators to open only change-password', () => {
    const guards = access({
      session: {
        status: 'password_change_required',
        currentAdmin: {
          id: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
          username: 'admin',
          firstLoginRequired: true,
        },
      },
    });

    expect(guards.authenticated).toBe(false);
    expect(guards.passwordChangeAllowed).toBe(true);
  });

  it('does not treat Umi access as a business RBAC source', () => {
    const guards = access({
      session: {
        status: 'authenticated',
        currentAdmin: {
          id: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
          username: 'admin',
          firstLoginRequired: false,
        },
      },
    });

    expect(Object.keys(guards).sort()).toEqual([
      'authenticated',
      'passwordChangeAllowed',
    ]);
  });
});
