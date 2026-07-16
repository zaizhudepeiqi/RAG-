const CSRF_COOKIE = 'rag_csrf';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

type RequestWithHeaders = {
  method?: string;
  headers?: object;
};

export function getCsrfToken(): string | undefined {
  if (typeof document === 'undefined') {
    return undefined;
  }
  for (const item of document.cookie.split(';')) {
    const [name, ...valueParts] = item.trim().split('=');
    if (name !== CSRF_COOKIE) {
      continue;
    }
    const value = valueParts.join('=');
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
  return undefined;
}

export function withCsrfHeader<T extends RequestWithHeaders>(config: T): T {
  const method = (config.method ?? 'GET').toUpperCase();
  const csrfToken = getCsrfToken();
  if (!UNSAFE_METHODS.has(method) || !csrfToken) {
    return config;
  }
  return {
    ...config,
    headers: {
      ...config.headers,
      'X-CSRF-Token': csrfToken,
    },
  } as T;
}
