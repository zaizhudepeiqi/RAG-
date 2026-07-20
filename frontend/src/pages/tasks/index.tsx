import { ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import type { TableProps } from 'antd';
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import React, { useState } from 'react';
import { toApiClientError } from '@/features/api/errors';
import {
  useOperationQuery,
  useOperationsQuery,
} from '@/features/tasks/queries';

const STATUS_LABEL: Record<API.OperationStatus, string> = {
  queued: '排队中',
  running: '执行中',
  succeeded: '成功',
  partial_succeeded: '部分成功',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_COLOR: Record<API.OperationStatus, string> = {
  queued: 'default',
  running: 'processing',
  succeeded: 'success',
  partial_succeeded: 'warning',
  failed: 'error',
  cancelled: 'default',
};

function formatTime(value?: string | null): string {
  return value
    ? new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'short',
        timeStyle: 'medium',
      }).format(new Date(value))
    : '-';
}

function QueryErrorAlert({
  error,
  onRetry,
  retryLabel,
}: {
  error: unknown;
  onRetry: () => void;
  retryLabel: string;
}) {
  const apiError = toApiClientError(error);
  return (
    <Alert
      type="error"
      showIcon
      title={apiError.message}
      description={
        apiError.traceId ? `追踪 ID：${apiError.traceId}` : undefined
      }
      action={
        <Button
          aria-label={retryLabel}
          icon={<ReloadOutlined />}
          onClick={onRetry}
        >
          重试
        </Button>
      }
    />
  );
}

export default function TasksPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>();
  const [selectedId, setSelectedId] = useState<string>();
  const list = useOperationsQuery({ page, pageSize: 20, status });
  const detail = useOperationQuery(selectedId);

  const columns: TableProps<API.OperationDetail>['columns'] = [
    {
      title: '任务类型',
      dataIndex: 'taskType',
      render: (value: string) => (
        <Typography.Text code>{value}</Typography.Text>
      ),
    },
    { title: '目标类型', dataIndex: 'targetType' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (value: API.OperationStatus) => (
        <Tag color={STATUS_COLOR[value]}>{STATUS_LABEL[value]}</Tag>
      ),
    },
    {
      title: '进度',
      render: (_, operation) => (
        <Progress
          size="small"
          percent={
            operation.progressTotal
              ? Math.min(
                  100,
                  Math.round(
                    (operation.progressCurrent / operation.progressTotal) * 100,
                  ),
                )
              : undefined
          }
          status={operation.status === 'failed' ? 'exception' : 'normal'}
        />
      ),
    },
    {
      title: '排队时间',
      dataIndex: 'queuedAt',
      render: (value: string) => formatTime(value),
    },
  ];

  return (
    <PageContainer
      title={
        <Typography.Title level={2} style={{ fontSize: 20, margin: 0 }}>
          任务
        </Typography.Title>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 180 }}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          options={Object.entries(STATUS_LABEL).map(([value, label]) => ({
            value,
            label,
          }))}
        />
        {list.error ? (
          <QueryErrorAlert
            error={list.error}
            retryLabel="重试任务列表"
            onRetry={() => void list.refetch()}
          />
        ) : null}
        <Table<API.OperationDetail>
          columns={columns}
          dataSource={list.data?.items}
          loading={list.isLoading}
          rowKey="operationId"
          onRow={(operation) => ({
            onClick: () => setSelectedId(operation.operationId),
          })}
          pagination={{
            current: page,
            pageSize: 20,
            total: list.data?.total,
            showSizeChanger: false,
            onChange: setPage,
          }}
        />
      </Space>
      <Drawer
        size={520}
        title="任务详情"
        open={Boolean(selectedId)}
        loading={detail.isLoading}
        onClose={() => setSelectedId(undefined)}
      >
        {detail.error ? (
          <QueryErrorAlert
            error={detail.error}
            retryLabel="重试任务详情"
            onRetry={() => void detail.refetch()}
          />
        ) : detail.data ? (
          <Descriptions
            column={1}
            items={[
              {
                key: 'id',
                label: '任务 ID',
                children: detail.data.operationId,
              },
              {
                key: 'type',
                label: '任务类型',
                children: detail.data.taskType,
              },
              {
                key: 'status',
                label: '状态',
                children: STATUS_LABEL[detail.data.status],
              },
              {
                key: 'stage',
                label: '当前阶段',
                children: detail.data.stageLabel ?? '-',
              },
              {
                key: 'queued',
                label: '排队时间',
                children: formatTime(detail.data.queuedAt),
              },
              {
                key: 'started',
                label: '开始时间',
                children: formatTime(detail.data.startedAt),
              },
              {
                key: 'finished',
                label: '完成时间',
                children: formatTime(detail.data.finishedAt),
              },
              {
                key: 'error',
                label: '错误',
                children: detail.data.errorMessage ?? '-',
              },
            ]}
          />
        ) : null}
      </Drawer>
    </PageContainer>
  );
}
