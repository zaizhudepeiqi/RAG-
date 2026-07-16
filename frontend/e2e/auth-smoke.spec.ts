import { expect, test } from '@playwright/test';

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required for the authentication smoke test`);
  }
  return value;
}

test('administrator authentication shell works through HttpOnly cookies', async ({
  page,
}) => {
  const username = requiredEnvironment('RAG_E2E_USERNAME');
  const password = requiredEnvironment('RAG_E2E_PASSWORD');
  const newPassword = requiredEnvironment('RAG_E2E_NEW_PASSWORD');

  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/login\?redirect=/);

  await page.getByPlaceholder('管理员账号').fill(username);
  await page.getByPlaceholder('密码').fill(password);
  await page.getByRole('button', { name: '登录' }).click();

  await expect(page).toHaveURL('/change-password');
  await page.getByLabel('当前密码').fill(password);
  await page.getByLabel('新密码', { exact: true }).fill(newPassword);
  await page.getByLabel('确认新密码').fill(newPassword);
  const healthResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/health/dependencies' &&
      response.request().method() === 'GET',
  );
  await page.getByRole('button', { name: '确认修改' }).click();

  await expect(page).toHaveURL('/dashboard');
  const healthResponse = await healthResponsePromise;
  expect(healthResponse.ok()).toBe(true);
  const health = (await healthResponse.json()) as {
    dependencies: Array<{ code: string }>;
  };
  expect(health.dependencies.length).toBeGreaterThan(0);
  await expect(page.getByText(health.dependencies[0].code)).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL('/dashboard');

  const operationsResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/operations' &&
      response.request().method() === 'GET',
  );
  await page.goto('/tasks');
  const operationsResponse = await operationsResponsePromise;
  expect(operationsResponse.ok()).toBe(true);
  const operations = (await operationsResponse.json()) as { items: unknown[] };
  expect(Array.isArray(operations.items)).toBe(true);
  await expect(page.getByRole('heading', { name: '任务' })).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();

  await page.getByText(username).click();
  await page.getByText('退出登录').click();
  await expect(page).toHaveURL('/login');
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/login\?redirect=/);
});
