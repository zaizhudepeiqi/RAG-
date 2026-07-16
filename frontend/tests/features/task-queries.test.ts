import {
  useOperationQuery,
  useOperationsQuery,
} from '@/features/tasks/queries';

jest.mock('@tanstack/react-query', () => ({
  useQuery: jest.fn((options) => options),
}));

jest.mock('@/services/ragApi/yiburenwu', () => ({
  operationsGet: jest.fn(),
  operationsList: jest.fn(),
}));

type QueryOptions = {
  refetchIntervalInBackground?: boolean;
  refetchInterval:
    | number
    | ((query?: { state: { data?: API.OperationDetail } }) => number | false);
};

describe('operation query polling', () => {
  const hidden = jest.spyOn(document, 'hidden', 'get');

  afterAll(() => hidden.mockRestore());

  it('recomputes a reduced list interval while the document is hidden', () => {
    const options = useOperationsQuery({
      page: 1,
      pageSize: 20,
    }) as unknown as QueryOptions;

    expect(options.refetchIntervalInBackground).toBe(true);
    expect(typeof options.refetchInterval).toBe('function');

    hidden.mockReturnValue(false);
    expect((options.refetchInterval as () => number)()).toBe(10_000);
    hidden.mockReturnValue(true);
    expect((options.refetchInterval as () => number)()).toBe(60_000);
  });

  it('slows detail polling in the background and stops at a terminal status', () => {
    const options = useOperationQuery(
      '2777136d-608c-4c26-8b7a-bc6e15cd9158',
    ) as unknown as QueryOptions;
    const interval = options.refetchInterval as (query: {
      state: { data?: API.OperationDetail };
    }) => number | false;

    expect(options.refetchIntervalInBackground).toBe(true);

    hidden.mockReturnValue(false);
    expect(interval({ state: {} })).toBe(5_000);
    hidden.mockReturnValue(true);
    expect(interval({ state: {} })).toBe(30_000);
    expect(
      interval({
        state: { data: { status: 'succeeded' } as API.OperationDetail },
      }),
    ).toBe(false);
  });
});
