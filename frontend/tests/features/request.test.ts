import { ApiClientError, toApiClientError } from '@/features/api/errors';
import { getCsrfToken, withCsrfHeader } from '@/features/auth/cookies';

describe('request security and errors', () => {
  afterEach(() => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom does not implement the Cookie Store API.
    document.cookie = 'rag_csrf=; Max-Age=0; Path=/';
    jest.restoreAllMocks();
  });

  it('never reads or writes an access token in localStorage', () => {
    const getItem = jest.spyOn(Storage.prototype, 'getItem');
    const setItem = jest.spyOn(Storage.prototype, 'setItem');
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom does not implement the Cookie Store API.
    document.cookie = 'rag_csrf=csrf-value; Path=/';

    expect(getCsrfToken()).toBe('csrf-value');
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });

  it('adds X-CSRF-Token only to unsafe methods when rag_csrf exists', () => {
    // biome-ignore lint/suspicious/noDocumentCookie: jsdom does not implement the Cookie Store API.
    document.cookie = 'rag_csrf=csrf%20value; Path=/';

    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      expect(withCsrfHeader({ method, headers: {} }).headers).toMatchObject({
        'X-CSRF-Token': 'csrf value',
      });
    }
    for (const method of ['GET', 'HEAD', 'OPTIONS']) {
      expect(
        withCsrfHeader({ method, headers: {} }).headers,
      ).not.toHaveProperty('X-CSRF-Token');
    }
  });

  it('preserves backend message, code, details and traceId in ApiClientError', () => {
    const error = toApiClientError({
      response: {
        status: 409,
        data: {
          code: 'RESOURCE_REVISION_CONFLICT',
          message: '资源已更新',
          details: { currentRevision: 4 },
          traceId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
        },
      },
    });

    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({
      status: 409,
      code: 'RESOURCE_REVISION_CONFLICT',
      message: '资源已更新',
      details: { currentRevision: 4 },
      traceId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
    });
  });
});
