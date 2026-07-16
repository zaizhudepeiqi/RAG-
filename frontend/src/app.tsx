import type { RequestOptions } from '@@/plugin-request/request';
import {
  DatabaseOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { Settings as LayoutSettings } from '@ant-design/pro-components';
import type { RequestConfig, RunTimeLayoutConfig } from '@umijs/max';
import { history, Link } from '@umijs/max';
import { App as AntdApp, Dropdown } from 'antd';
import React from 'react';
import { withCsrfHeader } from '@/features/auth/cookies';
import {
  loadSession,
  loginRedirect,
  registerUnauthorizedHandler,
  type SessionState,
  UNKNOWN_SESSION,
} from '@/features/auth/session';
import { authLogout, authMe } from '@/services/ragApi/guanliyuanrenzheng';
import defaultSettings from '../config/defaultSettings';
import { errorConfig } from './requestErrorConfig';

const LOGIN_PATH = '/login';
const CHANGE_PASSWORD_PATH = '/change-password';

export type InitialState = {
  session: SessionState;
  settings: Partial<LayoutSettings>;
};

export async function getInitialState(): Promise<InitialState> {
  const settings = defaultSettings as Partial<LayoutSettings>;
  if (history.location.pathname === LOGIN_PATH) {
    return { session: { status: 'unauthenticated' }, settings };
  }

  const session = await loadSession(UNKNOWN_SESSION, () => authMe({}));
  if (session.status === 'unauthenticated') {
    history.replace(loginRedirect(history.location));
  } else if (
    session.status === 'password_change_required' &&
    history.location.pathname !== CHANGE_PASSWORD_PATH
  ) {
    history.replace(CHANGE_PASSWORD_PATH);
  }
  return { session, settings };
}

export const layout: RunTimeLayoutConfig = ({
  initialState,
  setInitialState,
}) => {
  const clearSession = () => {
    void setInitialState((state) => ({
      ...state,
      session: { status: 'unauthenticated' },
      settings: state?.settings ?? {},
    }));
  };
  registerUnauthorizedHandler(() => {
    clearSession();
    if (history.location.pathname !== LOGIN_PATH) {
      history.replace(loginRedirect(history.location));
    }
  });

  const logout = async () => {
    try {
      await authLogout({});
    } finally {
      clearSession();
      history.replace(LOGIN_PATH);
    }
  };

  return {
    logo: <DatabaseOutlined />,
    menuItemRender: (item, dom) =>
      item.path ? (
        <Link to={item.path} prefetch>
          {dom}
        </Link>
      ) : (
        dom
      ),
    actionsRender: false,
    footerRender: false,
    avatarProps: {
      icon: <UserOutlined />,
      title: initialState?.session.currentAdmin?.username ?? '管理员',
      render: (_, avatarChildren) => (
        <Dropdown
          menu={{
            items: [
              {
                key: 'logout',
                icon: <LogoutOutlined />,
                label: '退出登录',
              },
            ],
            onClick: ({ key }) => {
              if (key === 'logout') {
                void logout();
              }
            },
          }}
        >
          <span>{avatarChildren}</span>
        </Dropdown>
      ),
    },
    onPageChange: () => {
      const status = initialState?.session.status;
      if (
        status === 'unauthenticated' &&
        history.location.pathname !== LOGIN_PATH
      ) {
        history.replace(loginRedirect(history.location));
      } else if (
        status === 'password_change_required' &&
        history.location.pathname !== CHANGE_PASSWORD_PATH
      ) {
        history.replace(CHANGE_PASSWORD_PATH);
      }
    },
    ...initialState?.settings,
  };
};

export const request: RequestConfig = {
  timeout: 30_000,
  withCredentials: true,
  ...errorConfig,
  requestInterceptors: [(config: RequestOptions) => withCsrfHeader(config)],
};

export function rootContainer(container: React.ReactNode) {
  return <AntdApp>{container}</AntdApp>;
}
