import { ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, Col, Row, Space, Tag, Typography } from 'antd';
import { useHealthDependenciesQuery } from '@/features/health/queries';

const STATUS = {
  healthy: { color: 'success', label: '正常' },
  degraded: { color: 'warning', label: '降级' },
  unhealthy: { color: 'error', label: '异常' },
  not_configured: { color: 'default', label: '未配置' },
} as const;

export default function DashboardPage() {
  const query = useHealthDependenciesQuery();

  return (
    <PageContainer
      title="运行状态"
      extra={
        <Button
          icon={<ReloadOutlined />}
          loading={query.isFetching}
          onClick={() => void query.refetch()}
        >
          刷新
        </Button>
      }
    >
      {query.error ? (
        <Alert type="error" showIcon title="无法读取依赖状态" />
      ) : null}
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Card loading={query.isLoading} size="small">
          <Space>
            <Typography.Text strong>整体状态</Typography.Text>
            {query.data ? (
              <Tag color={STATUS[query.data.status].color}>
                {STATUS[query.data.status].label}
              </Tag>
            ) : null}
            <Typography.Text type="secondary">
              {query.data?.version ? `版本 ${query.data.version}` : null}
            </Typography.Text>
          </Space>
        </Card>
        <Row gutter={[16, 16]}>
          {query.data?.dependencies.map((dependency) => (
            <Col xs={24} md={12} xl={8} key={dependency.code}>
              <Card size="small" title={dependency.code}>
                <Space orientation="vertical" size={8}>
                  <Tag color={STATUS[dependency.status].color}>
                    {STATUS[dependency.status].label}
                  </Tag>
                  <Typography.Text>{dependency.message}</Typography.Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Space>
    </PageContainer>
  );
}
