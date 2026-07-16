import { configUmiAlias, createConfig } from '@umijs/max/test.js';

export default async (): Promise<any> => {
  const config = await configUmiAlias({
    ...createConfig({
      target: 'browser',
    }),
  });
  return {
    ...config,
    testPathIgnorePatterns: ['/node_modules/', '<rootDir>/.worktrees/'],
    testEnvironmentOptions: {
      ...(config?.testEnvironmentOptions || {}),
      url: 'http://127.0.0.1:5173',
    },
    setupFiles: [...(config.setupFiles || []), './tests/setupTests.jsx'],
    globals: {
      ...config.globals,
      localStorage: null,
    },
  };
};
