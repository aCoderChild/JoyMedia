import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const source = process.env.JOYMEDIA_RENDER_SOURCE_PROJECT;
const existingEdit = process.env.JOYMEDIA_RENDER_EDIT_PROJECT;
const output = process.env.JOYMEDIA_RENDER_EVIDENCE || '/workspace/development/verification/rio-live-comfy-evidence.json';
const waitMs = Number(process.env.JOYMEDIA_LIVE_RENDER_WAIT_MS || 780_000);

test('RIO submits a real first-frame job and receives its image through Frappe', async ({ context, page }) => {
  test.skip(!session || !source || process.env.JOYMEDIA_LIVE_RENDER !== '1', 'Explicit live render opt-in required');
  test.setTimeout(900_000);
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  await page.goto('/joymedia/projects');
  const csrf = await page.evaluate(() => window.csrf_token);
  let edit = existingEdit;
  if (!edit) {
    const created = await context.request.post('/api/method/joymedia.services.project.versions.create_edit', {
      headers: { 'X-Frappe-CSRF-Token': csrf },
      form: { project_name: source, label: `RIO ComfyUI verification ${Date.now()}`, kind: 'Experiment', make_working: 'false' },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    edit = (await created.json()).message.edit;
  }
  const evidence = { source, edit, at: new Date().toISOString() };
  await fs.writeFile(output, JSON.stringify(evidence, null, 2));
  await page.goto(`/joymedia/projects/${edit}`);
  await expect(page.locator('[data-test="rio-studio"]')).toBeVisible();
  await expect(page.locator('.rio-node').first()).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  const projectResponse = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: edit } });
  expect(projectResponse.ok(), await projectResponse.text()).toBeTruthy();
  const project = (await projectResponse.json()).message.project;
  if (project.storyboard_approval_status !== 'Approved') {
    const approval = page.waitForResponse(r => r.url().includes('approve_project_storyboard') && r.request().method() === 'POST', { timeout: 90_000 });
    await page.locator('.rio-next-action').click();
    const approved = await approval;
    expect(approved.ok(), await approved.text()).toBeTruthy();
    evidence.storyboard_approved = true;
    await fs.writeFile(output, JSON.stringify(evidence, null, 2));
  }

  const framesUrl = '/api/method/joymedia.services.keyframes.stage.get_project_keyframes';
  const readFrames = async () => {
    const response = await context.request.get(framesUrl, { params: { project_name: edit } });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()).message;
  };
  const framesBefore = await readFrames();
  const requestedIndex = process.env.JOYMEDIA_RENDER_SHOT_INDEX;
  const targetIndex = requestedIndex == null
    ? framesBefore.findIndex(row => row.needs_keyframe && (!row.url || row.stale))
    : Number(requestedIndex);
  expect(targetIndex, 'Expected an existing scene needing a first frame').toBeGreaterThanOrEqual(0);
  const first = framesBefore[targetIndex];
  expect(first?.shot).toBeTruthy();
  expect(first.needs_keyframe, 'The selected shot is not a first-frame scene boundary').toBe(true);
  evidence.first_shot = first.shot;
  await fs.writeFile(output, JSON.stringify(evidence, null, 2));
  // Approval can queue previews automatically. If it did not, use the RIO scene control.
  const workspaceResponse = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: edit } });
  const workspace = (await workspaceResponse.json()).message;
  if (!workspace.project.busy_shots?.length && !first.url) {
    const submitted = page.waitForResponse(r => r.url().includes('generate_keyframes') && r.request().method() === 'POST', { timeout: 90_000 });
    await page.locator('.rio-node').nth(targetIndex).getByRole('button', { name: '✨ F0' }).click();
    const response = await submitted;
    expect(response.ok(), await response.text()).toBeTruthy();
    evidence.ui_submission = (await response.json()).message;
    await fs.writeFile(output, JSON.stringify(evidence, null, 2));
  }
  let latest;
  await expect.poll(async () => {
    latest = (await readFrames()).find(row => row.shot === first.shot);
    return Boolean(latest?.url && !latest.stale);
  }, { timeout: waitMs, intervals: [5000] }).toBeTruthy();
  evidence.frame = { shot: latest.shot, url: latest.url, status: latest.status, stale: latest.stale };
  const image = await context.request.get(latest.url);
  expect(image.ok()).toBeTruthy();
  evidence.image_bytes = (await image.body()).length;
  expect(evidence.image_bytes).toBeGreaterThan(1000);
  await page.reload();
  await expect(page.locator('.rio-node').nth(targetIndex).locator('img').first()).toBeVisible();
  await fs.writeFile(output, JSON.stringify(evidence, null, 2));
});
