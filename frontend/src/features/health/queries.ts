import { useQuery } from '@tanstack/react-query';
import { healthDependencies } from '@/services/ragApi/xitongjiankang';

export function useHealthDependenciesQuery() {
  return useQuery({
    queryKey: ['health', 'dependencies'],
    queryFn: () => healthDependencies(),
    refetchInterval: 30_000,
  });
}
