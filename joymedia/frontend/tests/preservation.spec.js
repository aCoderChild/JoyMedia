import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const project = process.env.SHERA_TEST_PROJECT;
const user = process.env.JOYMEDIA_TEST_USER;
const password = process.env.JOYMEDIA_TEST_PASSWORD;
const session = process.env.JOYMEDIA_TEST_SESSION;
let requestHeaders = {};

test.describe('general source-art preservation controls', () => {
  test.skip(!project || (!session && (!user || !password)), 'Provide a test project and authorized account');
  test.beforeEach(async ({ context, page }) => {
    if (session) {
      const cookies=JSON.parse(await fs.readFile(session,'utf8'));
      await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
    } else {
      const login = await context.request.post('/api/method/login', { form: { usr: user, pwd: password } });
      expect(login.ok()).toBeTruthy();
    }
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
    await page.goto('/joymedia/projects');
    const csrf = await page.evaluate(() => window.csrf_token);
    requestHeaders = csrf ? {'X-Frappe-CSRF-Token':csrf} : {};
  });

  test('source artwork editor uses real private image and video surfaces', async ({ page, context }) => {
    const response = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: project } });
    expect(response.ok()).toBeTruthy();
    const workspace = (await response.json()).message;
    if (workspace.final_video) expect(['review', 'release']).toContain(workspace.final_video.export_purpose);
    const product = workspace.assets.find(asset => asset.reference_role === 'Product' && asset.media_type === 'Image');
    expect(product).toBeTruthy();
    await page.goto(`/joymedia/projects/${project}?editor=advanced`);
    const access = await context.request.get('/api/method/joymedia.services.partners.get_access', {params:{project_name:project}});
    if (!(await access.json()).message.can_use_advanced_editor) {
      await expect(page.locator('[data-test="client-video"]')).toBeVisible();
      await expect(page.locator('[data-test="restore-artwork"]')).toHaveCount(0);
      return;
    }
    await page.locator('[data-test="restore-artwork"]').first().click();
    const dialog = page.locator('[data-test="source-art-repair"]');
    await expect(dialog).toBeVisible();
    await dialog.locator('[data-test="repair-artwork"]').selectOption(product.asset_version);
    for (const side of ['source','target']) {
      const canvas = dialog.locator(`[data-test="repair-${side}"]`);
      await expect.poll(() => canvas.evaluate(element => element.width)).toBeGreaterThan(300);
      const box = await canvas.boundingBox();
      for (const [x,y] of [[.2,.2],[.8,.2],[.8,.8],[.2,.8]]) {
        await canvas.click({ position: { x: box.width*x, y: box.height*y } });
      }
    }
    await expect(dialog.locator('[data-test="repair-submit"]')).toBeDisabled();
    await dialog.getByLabel('Match scene lighting', {exact:true}).check();
    await expect(dialog).toContainText('Check the brand colors');
    await expect(dialog.locator('[data-test="repair-submit"]')).toBeDisabled();
    await dialog.getByLabel('Nothing passes in front of the selected surface.', {exact:true}).check();
    await expect(dialog.locator('[data-test="repair-submit"]')).toBeEnabled();
    // Geometry is intentionally arbitrary: this test verifies the control UI,
    // never submits an unauthored repair or queues another paid model job.
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(dialog).not.toBeVisible();
  });

  test('release export rejects unreviewed footage without queuing a render', async ({ context }) => {
    const response = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: project } });
    const workspace = (await response.json()).message;
    test.skip(!workspace.storyboard.some(shot => shot.brand_review?.status === 'Needs Review'), 'This fixture already has all takes reviewed');
    const release = await context.request.post('/api/method/joymedia.services.editing.export_jobs.queue_project_timeline_export', {headers:requestHeaders, data: { project_name: project, purpose: 'release' } });
    expect(release.status(), await release.text()).toBe(417);
    expect(await release.text()).toContain('Release blocked');
  });

  test('stale take and raw output path cannot enter repair execution', async ({ context }) => {
    const response = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: project } });
    const workspace = (await response.json()).message;
    const shot = workspace.storyboard[0];
    for (const [take,planes] of [['STALE-TAKE', []], [shot.selected_output_asset_version, [{ artwork:'asset', source_quad:[], target_quad:[], output_path:'/tmp/unapproved-output' }]]]) {
      const repair = await context.request.post('/api/method/joymedia.services.consistency.repair.queue_source_art_repair', {headers:requestHeaders, data: { project_name: project, shot_name: shot.name, expected_take: take, planes } });
      expect(repair.status(), await repair.text()).toBe(417);
    }
  });
});
