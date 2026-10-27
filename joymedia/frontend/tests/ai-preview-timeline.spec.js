import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const project = process.env.JOYMEDIA_AI_PREVIEW_PROJECT || 'PRJ-02643';

test('a complete AI preview exposes its film and scene-level decisions together', async ({ page, context }) => {
  test.skip(!session, 'Authorized live account required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="client-video"] video')).toBeVisible();
  await expect(page.locator('[data-test^="select-scene-"]')).toHaveCount(6);
  await page.locator('[data-test="select-scene-0"]').click();
  await expect(page.getByRole('button', { name: /Retry clip|Tạo lại clip/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Retry first frame|Vẽ lại ảnh đầu/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Choose another take|Chọn bản khác/ })).toBeVisible();
  await page.getByRole('button', { name: /Back to full video|Về video hoàn chỉnh/ }).click();
  await expect(page.locator('[data-test="client-video"] video')).toBeVisible();
});
