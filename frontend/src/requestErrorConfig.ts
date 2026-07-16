import type { RequestConfig } from '@umijs/max';
import { message } from 'antd';
import { toApiClientError } from '@/features/api/errors';
import { clearUnauthorizedSession } from '@/features/auth/session';

export const errorConfig: RequestConfig = {
  errorConfig: {
    errorHandler: (error, options) => {
      const apiError = toApiClientError(error);
      if (apiError.status === 401) {
        clearUnauthorizedSession();
      }
      if (!options?.skipErrorHandler && apiError.status === undefined) {
        message.error(apiError.message);
      }
      throw apiError;
    },
  },
};
