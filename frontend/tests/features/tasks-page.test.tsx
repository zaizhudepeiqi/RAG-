import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { ApiClientError } from '@/features/api/errors';
import {
  useOperationQuery,
  useOperationsQuery,
} from '@/features/tasks/queries';
import TasksPage from '@/pages/tasks';

jest.mock('@/features/tasks/queries', () => ({
  useOperationQuery: jest.fn(),
  useOperationsQuery: jest.fn(),
}));

const useOperationQueryMock = jest.mocked(useOperationQuery);
const useOperationsQueryMock = jest.mocked(useOperationsQuery);

function apiError(message: string) {
  return new ApiClientError({
    message,
    status: 503,
    code: 'DEPENDENCY_UNAVAILABLE',
    traceId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
  });
}

describe('tasks page errors', () => {
  const refetchList = jest.fn();
  const refetchDetail = jest.fn();
  const getComputedStyle = window.getComputedStyle;
  const getComputedStyleSpy = jest
    .spyOn(window, 'getComputedStyle')
    .mockImplementation((element) => getComputedStyle.call(window, element));

  afterAll(() => getComputedStyleSpy.mockRestore());

  beforeEach(() => {
    jest.clearAllMocks();
    useOperationQueryMock.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
      refetch: refetchDetail,
    } as never);
  });

  it('shows the backend list error and offers a retry action', () => {
    useOperationsQueryMock.mockReturnValue({
      data: undefined,
      error: apiError('任务服务暂时不可用'),
      isLoading: false,
      refetch: refetchList,
    } as never);

    render(React.createElement(TasksPage));

    expect(screen.getByText('任务服务暂时不可用')).toBeTruthy();
    expect(screen.getByText(/2777136d-608c/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试任务列表' }));
    expect(refetchList).toHaveBeenCalledTimes(1);
  });

  it('shows the backend detail error and offers a retry action', () => {
    useOperationsQueryMock.mockReturnValue({
      data: {
        items: [
          {
            operationId: '2777136d-608c-4c26-8b7a-bc6e15cd9158',
            taskType: 'index_documents',
            targetType: 'knowledge_base',
            status: 'running',
            progressCurrent: 1,
            progressTotal: 2,
            queuedAt: '2026-07-16T10:00:00Z',
          } as API.OperationDetail,
        ],
        total: 1,
      },
      error: null,
      isLoading: false,
      refetch: refetchList,
    } as never);
    useOperationQueryMock.mockReturnValue({
      data: undefined,
      error: apiError('无法读取任务详情'),
      isLoading: false,
      refetch: refetchDetail,
    } as never);

    render(React.createElement(TasksPage));
    fireEvent.click(screen.getByText('index_documents'));

    expect(screen.getByText('无法读取任务详情')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试任务详情' }));
    expect(refetchDetail).toHaveBeenCalledTimes(1);
  });
});
