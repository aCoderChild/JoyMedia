import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const project = process.env.JOYMEDIA_PROGRESSIVE_PREVIEW_PROJECT || 'PRJ-02643';

test('an automatic variant exposes one silent rough cut and its scene states', async ({ page, context }) => {
  test.skip(!session, 'Authorized live account required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="progressive-film-preview"]')).toBeVisible();
  await expect(page.locator('[data-test="progressive-film-player"]')).toBeVisible();
  await expect(page.locator('[data-test="progressive-film-preview"] li')).toHaveCount(6);
});
