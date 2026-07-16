export default [
  {
    path: '/login',
    layout: false,
    component: './login',
  },
  {
    path: '/change-password',
    name: '修改密码',
    icon: 'key',
    access: 'passwordChangeAllowed',
    component: './change-password',
  },
  {
    path: '/dashboard',
    name: '运行状态',
    icon: 'dashboard',
    access: 'authenticated',
    component: './dashboard',
  },
  {
    path: '/tasks',
    name: '任务',
    icon: 'unorderedList',
    access: 'authenticated',
    component: './tasks',
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    component: './exception/404',
    layout: false,
    path: '/*',
  },
];
