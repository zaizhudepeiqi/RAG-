import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { history, useModel } from '@umijs/max';
import { message } from 'antd';
import { toApiClientError } from '@/features/api/errors';
import { authLogin } from '@/services/ragApi/guanliyuanrenzheng';

function safeRedirect(search: string): string {
  const redirect = new URLSearchParams(search).get('redirect');
  return redirect?.startsWith('/') && !redirect.startsWith('//')
    ? redirect
    : '/dashboard';
}

export default function LoginPage() {
  const { setInitialState } = useModel('@@initialState');

  return (
    <main
      style={{
        alignItems: 'center',
        background: '#f4f6f8',
        display: 'flex',
        minHeight: '100vh',
        padding: 24,
      }}
    >
      <div
        style={{
          background: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: 8,
          margin: '0 auto',
          maxWidth: 420,
          padding: '28px 32px 12px',
          width: '100%',
        }}
      >
        <LoginForm<API.LoginRequest>
          title="企业 RAG 知识库"
          subTitle="管理控制台"
          onFinish={async (values) => {
            try {
              const result = await authLogin(values);
              await setInitialState((state) => ({
                ...state,
                settings: state?.settings ?? {},
                session: {
                  status: result.firstLoginRequired
                    ? 'password_change_required'
                    : 'authenticated',
                  currentAdmin: result.admin,
                },
              }));
              history.replace(
                result.firstLoginRequired
                  ? '/change-password'
                  : safeRedirect(history.location.search),
              );
              return true;
            } catch (error) {
              message.error(toApiClientError(error).message);
              return false;
            }
          }}
        >
          <ProFormText
            name="username"
            fieldProps={{
              autoComplete: 'username',
              prefix: <UserOutlined />,
            }}
            placeholder="管理员账号"
            rules={[{ required: true, message: '请输入管理员账号' }]}
          />
          <ProFormText.Password
            name="password"
            fieldProps={{
              autoComplete: 'current-password',
              prefix: <LockOutlined />,
            }}
            placeholder="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          />
        </LoginForm>
      </div>
    </main>
  );
}
