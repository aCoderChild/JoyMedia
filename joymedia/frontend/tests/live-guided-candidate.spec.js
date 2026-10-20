import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const input = process.env.JOYMEDIA_GUIDED_CASE, session = process.env.JOYMEDIA_TEST_SESSION;
test('real UI creates and plays an isolated motion-guided ComfyUI candidate', async ({ page, context }) => {
  test.skip(process.env.JOYMEDIA_LIVE_RENDER !== '1' || !input || !session, 'Explicit live opt-in required');
  test.setTimeout(1800000);
  const data = JSON.parse(await fs.readFile(input, 'utf8')), output = path.dirname(input);
  const label = data.label || 'paw';
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  await page.goto(`/joymedia/projects/${data.project}?editor=advanced`);
  const panel = page.locator('[data-test="storyboard-panel"]').nth(data.index);
  await panel.locator('[data-test="guide-motion"]').click();
  const dialog = page.locator('[data-test="guided-candidate"]');
  for (const role of ['control_video', 'identity_reference', 'control_mask']) if (data[role]) {
    await expect(dialog.locator(`[data-test="${role}"] option[value="${data[role]}"]`)).toHaveCount(1, { timeout: 30000 });
    await dialog.locator(`[data-test="${role}"]`).selectOption(data[role]);
  }
  if (data.instruction) await dialog.locator('[data-test="guided-instruction"]').fill(data.instruction);
  const pending = page.waitForResponse(r => r.url().endsWith('/api/method/joymedia.services.generation.guided.queue_guided_candidate'), { timeout: 120000 });
  await dialog.locator('[data-test="guided-submit"]').click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = (await response.json()).message;
  await fs.writeFile(path.join(output, `guided-${label}-admission.json`), JSON.stringify(result, null, 2));
  const video = dialog.locator('[data-test="guided-video"]');
  await expect.poll(async () => {
    const failure = dialog.locator('[role="alert"]');
    if (await failure.count() && (await failure.textContent())?.trim()) throw new Error(await failure.textContent());
    return video.isVisible();
  }, { timeout: 1500000, intervals: [4000] }).toBeTruthy();
  await expect(dialog.locator('[data-test="guided-use"]')).toBeVisible({ timeout: 30000 });
  const media = await context.request.get(await video.getAttribute('src'));
  expect(media.ok()).toBeTruthy();
  await fs.writeFile(path.join(output, `guided-${label}-candidate.mp4`), await media.body());
  await video.evaluate(async v => { v.muted = true; await v.play(); });
  await expect.poll(() => video.evaluate(v => v.currentTime), { timeout: 15000 }).toBeGreaterThan(0.25);
  await page.screenshot({ path: path.join(output, `guided-${label}-live-playback.png`), fullPage: true });
  const workspace = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: data.project } });
  const state = (await workspace.json()).message;
  expect(state.storyboard.find(s => s.name === data.shot).selected_output_asset_version).toBe(data.expected_take);
  await fs.writeFile(path.join(output, `guided-${label}-ui-result.json`), JSON.stringify({ ...result, selected_take_unchanged: true, playback: true }, null, 2));
});

test('stale selection and cross-project candidate access are rejected', async ({ page, context }) => {
  test.skip(process.env.JOYMEDIA_LIVE_RENDER !== '1' || !input || !session, 'Explicit live opt-in required');
  test.setTimeout(120000);
  const data = JSON.parse(await fs.readFile(input, 'utf8'));
  const queued = JSON.parse(await fs.readFile(path.join(path.dirname(input), `guided-${data.label || 'paw'}-admission.json`), 'utf8'));
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
  await page.goto(`/joymedia/projects/${data.project}?editor=advanced`);
  const csrf = await page.evaluate(() => window.csrf_token);
  await context.setExtraHTTPHeaders({ 'X-Frappe-CSRF-Token': csrf });
  const stale = await context.request.post('/api/method/joymedia.services.generation.guided.use_guided_candidate', { form: { project_name: data.project, run_name: queued.run, expected_take: 'STALE' } });
  expect(stale.status()).toBe(417);
  const other = await context.request.get('/api/method/joymedia.services.generation.guided.guided_candidate_status', { params: { project_name: 'PRJ-02512', run_name: queued.run } });
  expect(other.status()).toBe(403);
  const workspace = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: data.project } });
  const state = (await workspace.json()).message;
  expect(state.storyboard.find(s => s.name === data.shot).selected_output_asset_version).toBe(data.expected_take);
  await fs.writeFile(path.join(path.dirname(input), `guided-${data.label || 'paw'}-guards.json`), JSON.stringify({ stale: stale.status(), cross_project: other.status(), selected_take_unchanged: true }, null, 2));
});
