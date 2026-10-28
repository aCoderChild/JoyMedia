import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const project = process.env.JOYMEDIA_UX_PROJECT;

test('studio loads usable prompt patterns from Frappe', async ({ context, page }) => {
  test.skip(!session || !project, 'Authorized live project and session required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="rio-studio"]')).toBeVisible();
  const response = page.waitForResponse(response => response.url().includes('joymedia.api.prompt_templates.list_prompt_templates'));
  await page.locator('[data-test="rio-templates-toggle"]').click();
  expect((await response).ok()).toBeTruthy();
  await expect(page.locator('[data-test="rio-template-library"] .rio-template-item')).toHaveCount(3);
  await expect(page.locator('[data-test="rio-template-library"]')).toContainText('Shera · Video 33');
  await expect(page.locator('[data-test="rio-template-library"]')).toContainText('AUNTIE · Video 5');
  await expect(page.locator('[data-test="rio-template-library"]')).toContainText('Shera · Video 14');
  await expect(page.locator('.rio-prompt-heading').first()).toBeVisible();
});
