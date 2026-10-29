import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('original identities, prepared views and scene bindings remain distinct in the studio', async ({ page, context }) => {
  const session = process.env.JOYMEDIA_TEST_SESSION;
  const project = process.env.JOYMEDIA_REGISTRY_PROJECT;
  test.skip(!session || !project, 'Authorized project and session required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  const writes = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && /approve|generate_keyframes|generate_video|retry_product_variant|create_product_batch/.test(request.url())) writes.push(request.url());
  });
  await page.goto(`/joymedia/projects/${project}`);
  await page.locator('[data-test="rio-script-outputs"]').click();
  const registry = page.locator('[data-test="reference-registry"]').last();
  await expect(registry).toBeVisible();
  await expect(registry.locator('[data-test="registry-subject"]')).toHaveCount(2);
  const mascot = registry.locator('[data-test="registry-subject"]').filter({ hasText: 'Character / mascot' });
  await expect(mascot).toHaveCount(1);
  await expect(mascot.locator('[data-test="registry-view"]')).toHaveCount(2);
  await expect(mascot).toContainText('two small round ears');
  await expect(registry).toContainText(/Inferred angle|Needs verification/);
  const mapping = registry.locator('[data-test="scene-reference-map"]');
  await mapping.locator('summary').click();
  await expect(mapping.locator('ol > li')).toHaveCount(5);
  await expect(mapping.locator('ol > li').last()).toContainText('No physical cast');
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});
