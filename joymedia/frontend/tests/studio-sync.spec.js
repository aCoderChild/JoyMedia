import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const project = process.env.JOYMEDIA_SYNC_PROJECT;

test('Studio picks up a completed planning snapshot without a render run', async ({ context, page }) => {
  test.skip(!session || !project, 'Authorized live project and session required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({
    name, value, url: 'http://127.0.0.1:8000',
  })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'vi'));

  const response = await context.request.get(
    `http://127.0.0.1:8000/api/method/joymedia.api.projects.get_project_workspace?name=${encodeURIComponent(project)}`,
  );
  expect(response.ok()).toBeTruthy();
  const initial = (await response.json()).message;
  expect(initial.storyboard?.length).toBeGreaterThan(0);
  await page.route('**/api/method/joymedia.api.projects.get_project_workspace*', async route => {
    await route.fulfill({ json: {
      message: {
        ...initial,
        project: { ...initial.project, planning_status: 'Running', status: 'Planning' },
        production: null,
        storyboard: [],
      },
    } });
  });
  await page.route('**/api/method/joymedia.api.projects.refresh_project_studio*', async route => {
    await route.fulfill({ json: {
      message: {
        ...initial,
        project: { ...initial.project, planning_status: 'Completed', status: 'Draft' },
        production: null,
      },
    } });
  });

  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('.rio-node').first()).toBeVisible();
  await expect(page.locator('.rio-status')).not.toContainText('Đang xử lý');
});
