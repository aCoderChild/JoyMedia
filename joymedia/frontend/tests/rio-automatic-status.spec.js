import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('automatic planning failure replaces the empty manual editor', async ({ context, page }) => {
  const session = process.env.JOYMEDIA_TEST_SESSION;
  const project = process.env.JOYMEDIA_FAILED_AUTOMATIC_PROJECT;
  test.skip(!session || !project, 'Authorized failed automatic project and session required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'vi'));
  await page.route('**/api/method/joymedia.api.creative.get_project_batches**', route => route.fulfill({ json: { message: [{ name: 'batch', source_project: project, delivery_mode: 'automatic', variants: [{ project, index: 1, status: 'Needs Attention', error: 'Product/mascot reference analysis is missing: product' }] }] } }));
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="rio-automatic-status"]')).toContainText('phân tích');
  await expect(page.locator('[data-test="rio-empty-storyboard"]')).toHaveCount(0);
  await expect(page.locator('.rio-status')).toContainText('Cần xử lý');
});
