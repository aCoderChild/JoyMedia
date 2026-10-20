import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const input = process.env.JOYMEDIA_SCENE_CASES;
const session = process.env.JOYMEDIA_TEST_SESSION;
const api = '/api/method/';

test.describe('live temporal scene review', () => {
  test.skip(process.env.JOYMEDIA_LIVE_REVIEW !== '1' || !input || !session, 'Explicit real-review manifest and session required');
  test.setTimeout(1200000);
  test('review actual generated takes through UI and inspect their exact-take findings', async ({ page, context }) => {
    const data = JSON.parse(await fs.readFile(input, 'utf8'));
    const root = path.dirname(input);
    const fixture = JSON.parse(await fs.readFile(path.join(root, 'fixture.json'), 'utf8'));
    const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
    await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
    await page.goto(`/joymedia/projects/${data.project}?editor=advanced`);
    const csrf = await page.evaluate(() => window.csrf_token);
    await context.setExtraHTTPHeaders({ 'X-Frappe-CSRF-Token': csrf });
    const get = async (method, params) => {
      const response = await context.request.get(api + method, { params, maxRetries: 2 });
      expect(response.ok(), await response.text()).toBeTruthy();
      return (await response.json()).message;
    };
    const workspace = () => get('joymedia.api.projects.get_project_workspace', { name: data.project });
    let snapshot;
    await expect.poll(async () => {
      snapshot = await workspace();
      return data.cases.every(c => snapshot.storyboard.find(s => s.name === c.shot).selected_output_asset_version !== fixture.shots.find(s => s.name === c.shot).initial_take && !snapshot.project.busy_shots.includes(c.shot));
    }, { timeout: 900000, intervals: [5000] }).toBeTruthy();
    const events = [];
    for (const c of data.cases) {
      await expect.poll(async () => (await workspace()).storyboard.find(s => s.name === c.shot).consistency_status, { timeout: 300000, intervals: [2000] }).not.toBe('Checking');
      await page.reload();
      const before = await workspace();
      const shot = before.storyboard.find(s => s.name === c.shot);
      const wrong = await context.request.post(api + 'joymedia.services.review.consistency.request_scene_check', { form: { project_name: data.project, shot_name: c.shot, expected_take: 'STALE-TAKE' } });
      expect(wrong.status()).toBe(417);
      const foreign = await context.request.post(api + 'joymedia.services.review.consistency.get_scene_check_evidence', { form: { project_name: data.project, shot_name: fixture.shots[0].source, expected_take: shot.selected_output_asset_version } });
      expect(foreign.status()).toBe(403);
      const panel = page.locator('[data-test="storyboard-panel"]').nth(c.index);
      const pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(api + 'joymedia.services.review.consistency.request_scene_check'));
      await panel.locator('[data-test="check-scene"]').click();
      const queued = await pending;
      expect(queued.ok()).toBeTruthy();
      expect((await queued.json()).message.take).toBe(shot.selected_output_asset_version);
      await expect.poll(async () => (await workspace()).storyboard.find(s => s.name === c.shot).consistency_status, { timeout: 300000, intervals: [2000] }).not.toBe('Checking');
      const report = await get('joymedia.services.review.consistency.get_scene_check_evidence', { project_name: data.project, shot_name: c.shot, expected_take: shot.selected_output_asset_version });
      expect(report.asset_version).toBe(shot.selected_output_asset_version);
      expect(report.samples.length).toBeGreaterThan(4);
      expect(report.samples.length).toBeLessThanOrEqual(16);
      expect(report.results.some(r => r.dimension === 'action')).toBeTruthy();
      expect(report.results.some(r => r.dimension === 'physics')).toBeTruthy();
      expect(report.results.some(r => r.dimension === 'order')).toBeTruthy();
      await panel.locator('[data-test="scene-findings"]').click();
      await expect(page.getByText('Scene review findings', { exact: true })).toBeVisible();
      await expect(page.locator('[data-test="scene-check-findings"]')).toBeVisible();
      await page.screenshot({ path: path.join(root, `${c.shot}-findings.png`), fullPage: true });
      await page.getByRole('button', { name: 'Close', exact: true }).last().click();
      const after = await workspace();
      expect(after.production.name).toBe(before.production.name);
      expect(after.storyboard.find(s => s.name === c.shot).selected_output_asset_version).toBe(shot.selected_output_asset_version);
      await expect(page.locator('[data-test="release-export"]')).toBeDisabled();
      events.push({ shot: c.shot, take: shot.selected_output_asset_version, stale_request_status: wrong.status(), foreign_request_status: foreign.status(), report });
      await fs.writeFile(path.join(root, 'live-review-results.json'), JSON.stringify(events, null, 2));
    }
  });
});
