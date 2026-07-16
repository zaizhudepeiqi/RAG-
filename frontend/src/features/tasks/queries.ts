import { useQuery } from '@tanstack/react-query';
import { operationsGet, operationsList } from '@/services/ragApi/yiburenwu';

const TERMINAL_STATUSES = new Set<API.OperationStatus>([
  'succeeded',
  'partial_succeeded',
  'failed',
  'cancelled',
]);

export function useOperationsQuery(params: API.operationsListParams) {
  return useQuery({
    queryKey: ['operations', 'list', params],
    queryFn: () => operationsList(params),
    refetchInterval: () =>
      typeof document !== 'undefined' && document.hidden ? 60_000 : 10_000,
    refetchIntervalInBackground: true,
  });
}

export function useOperationQuery(operationId?: string) {
  return useQuery({
    queryKey: ['operations', operationId],
    queryFn: () => operationsGet({ operationId: operationId as string }),
    enabled: Boolean(operationId),
    refetchInterval: (query) => {
      const operation = query.state.data as API.OperationDetail | undefined;
      if (operation && TERMINAL_STATUSES.has(operation.status)) {
        return false;
      }
      return typeof document !== 'undefined' && document.hidden
        ? 30_000
        : 5_000;
    },
    refetchIntervalInBackground: true,
  });
}
