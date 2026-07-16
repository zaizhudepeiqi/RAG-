import {
  PageContainer,
  ProForm,
  ProFormText,
} from '@ant-design/pro-components';
import { history, useModel } from '@umijs/max';
import { Card, message } from 'antd';
import { toApiClientError } from '@/features/api/errors';
import {
  authChangePassword,
  authMe,
} from '@/services/ragApi/guanliyuanrenzheng';

export default function ChangePasswordPage() {
  const { setInitialState } = useModel('@@initialState');

  return (
    <PageContainer title="修改密码">
      <Card style={{ maxWidth: 560 }}>
        <ProForm<API.ChangePasswordRequest>
          layout="vertical"
          submitter={{ searchConfig: { submitText: '确认修改' } }}
          onFinish={async (values) => {
            try {
              await authChangePassword({}, values);
              const currentAdmin = await authMe({});
              await setInitialState((state) => ({
                ...state,
                settings: state?.settings ?? {},
                session: { status: 'authenticated', currentAdmin },
              }));
              message.success('密码已更新');
              history.replace('/dashboard');
              return true;
            } catch (error) {
              message.error(toApiClientError(error).message);
              return false;
            }
          }}
        >
          <ProFormText.Password
            name="oldPassword"
            label="当前密码"
            fieldProps={{ autoComplete: 'current-password' }}
            rules={[{ required: true, message: '请输入当前密码' }]}
          />
          <ProFormText.Password
            name="newPassword"
            label="新密码"
            fieldProps={{ autoComplete: 'new-password' }}
            rules={[
              { required: true, min: 12, message: '新密码至少 12 个字符' },
            ]}
          />
          <ProFormText.Password
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            fieldProps={{ autoComplete: 'new-password' }}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  return !value || value === getFieldValue('newPassword')
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          />
        </ProForm>
      </Card>
    </PageContainer>
  );
}
