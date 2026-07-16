export class ApiClientError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly details?: unknown;
  readonly traceId?: string;

  constructor(options: {
    message: string;
    status?: number;
    code?: string;
    details?: unknown;
    traceId?: string;
  }) {
    super(options.message);
    this.name = 'ApiClientError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
    this.traceId = options.traceId;
  }
}

export function toApiClientError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error;
  }
  const source = error as {
    message?: unknown;
    response?: { status?: unknown; data?: unknown };
  };
  const data = source.response?.data as
    | {
        code?: unknown;
        details?: unknown;
        message?: unknown;
        traceId?: unknown;
      }
    | undefined;

  return new ApiClientError({
    message:
      typeof data?.message === 'string'
        ? data.message
        : typeof source.message === 'string'
          ? source.message
          : '请求失败',
    status:
      typeof source.response?.status === 'number'
        ? source.response.status
        : undefined,
    code: typeof data?.code === 'string' ? data.code : undefined,
    details: data?.details,
    traceId: typeof data?.traceId === 'string' ? data.traceId : undefined,
  });
}
