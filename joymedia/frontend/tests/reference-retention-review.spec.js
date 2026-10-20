import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const project = process.env.JOYMEDIA_RETENTION_TEST_PROJECT;
const shot = process.env.JOYMEDIA_RETENTION_TEST_SHOT;
const session = process.env.JOYMEDIA_TEST_SESSION;

test('an isolated edit exposes reviewed take selection and rejects a stale tab', async ({ page, context }) => {
  test.skip(!project || !shot || !session, 'Provide an isolated qualification edit, scene and authorized session');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  await page.goto(`/joymedia/projects/${project}`);
  const endpoint = '/api/method/joymedia.services.project.versions.get_history';
  const history = async () => {
    const response = await context.request.get(endpoint, { params: { project_name: project, kind: 'takes', shot_name: shot } });
    expect(response.ok()).toBeTruthy();
    return (await response.json()).message;
  };
  const before = await history();
  expect(before.family.current_edit).not.toBe(project);
  expect(before.can_select_takes).toBeTruthy();
  const selected = before.items.find(item => item.shot === shot && item.is_selected);
  const candidate = before.items.find(item => item.shot === shot && item.media_project === project && !item.is_selected);
  expect(selected).toBeTruthy();
  expect(candidate).toBeTruthy();
  await page.getByRole('button', { name: 'Version history', exact: true }).filter({ visible: true }).click();
  const dialog = page.locator('[data-test="project-history"]');
  await dialog.getByRole('button', { name: /^(Scene versions|Scene takes)$/ }).click();
  await dialog.locator('[data-test="history-scene-filter"]').selectOption(shot);
  const item = dialog.locator(`[data-version="${candidate.name}"]`);
  await expect(item.locator('[data-test="use-reviewed-take"]')).toBeVisible();
  const csrf = await page.evaluate(() => window.csrf_token);
  const stale = await context.request.post('/api/method/joymedia.services.generation.takes.use_reviewed_take', {
    headers: { 'X-Frappe-CSRF-Token': csrf },
    data: { project_name: project, shot_name: shot, asset_version: candidate.name, expected_current: '__stale_selection__' },
  });
  expect(stale.ok()).toBeFalsy();
  expect((await history()).items.find(row => row.is_selected)?.name).toBe(selected.name);
  if (process.env.JOYMEDIA_RETENTION_REVIEW_SCREENSHOT) {
    await page.screenshot({ path: process.env.JOYMEDIA_RETENTION_REVIEW_SCREENSHOT, fullPage: true });
  }
});
