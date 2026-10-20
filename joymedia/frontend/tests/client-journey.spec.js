import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { clientJourney } from '../src/utils/clientJourney.js';

const shots = [{ name: 'a' }, { name: 'b' }];
const base = { hasStory: true, shots, approved: true, frames: shots.map(s => ({ shot: s.name, needs_keyframe: true, url: '/preview.png', status: 'Approved', stale: false })), hasVideo: () => false };
const scenarios = [
  ['empty brief', { hasStory: false, shots: [] }, 'brief'],
  ['brief ready', { shots: [] }, 'plan'],
  ['storyboard review', { approved: false }, 'approve'],
  ['frames loading', { frames: null }, 'loading'],
  ['preview check failure', { framesError: true }, 'retry'],
  ['partial frame response', { frames: base.frames.slice(0, 1) }, 'loading'],
  ['missing preview', { frames: base.frames.map(f => ({ ...f, url: '' })) }, 'previews'],
  ['stale approval', { frames: base.frames.map(f => ({ ...f, stale: true })) }, 'previews'],
  ['one unapproved', { frames: [base.frames[0], { ...base.frames[1], status: 'Pending' }] }, 'review'],
  ['approved previews', {}, 'render'],
  ['continuation needs no frame', { frames: base.frames.map(f => ({ ...f, needs_keyframe: false, url: '' })) }, 'render'],
  ['some videos ready', { hasVideo: s => s.name === 'a' }, 'render'],
  ['all videos ready', { hasVideo: () => true }, 'watch'],
  ['old videos with revised first frames', {hasVideo:()=>true,frames:base.frames.map(f=>({...f,stale:true}))}, 'previews'],
  ['rendering', { busy: true, hasVideo: () => true }, 'working'],
  ['finishing', { finishing: true, hasVideo: () => true }, 'working'],
];
for (const [name, state, expected] of scenarios) test(`journey: ${name}`, () => expect(clientJourney({ ...base, ...state })).toBe(expected));

test.describe('live client navigation', () => {
  test.skip(!process.env.JOYMEDIA_TEST_SESSION || !process.env.JOYMEDIA_UX_PROJECT, 'Requires an authorized live session and existing video project');
  test('completed project guides client to playback without rerendering or approving takes', async ({ page, context }) => {
    const cookies = JSON.parse(await fs.readFile(process.env.JOYMEDIA_TEST_SESSION, 'utf8'));
    await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
    const mutations = [];
    page.on('request', req => { if (req.method() === 'POST' && /generate_project_video|generate_keyframes|set_keyframe_approval|approve_scene_brand/.test(req.url())) mutations.push(req.url()); });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`/joymedia/projects/${process.env.JOYMEDIA_UX_PROJECT}?editor=advanced`);
    const next = page.locator('[data-test="client-next-action"]');
    await expect(next).toHaveText(/Watch & edit video/, { timeout: 30000 });
    await expect(page.locator('[data-test="client-next-hint"]')).toContainText('Review selected takes before release');
    await expect(page.locator('[data-test="readiness"] details')).not.toHaveAttribute('open');
    await expect(page.locator('[data-test="release-export"]')).toBeDisabled();
    if (process.env.JOYMEDIA_UX_SCREENSHOT) await page.screenshot({ path: process.env.JOYMEDIA_UX_SCREENSHOT.replace(/\.png$/, '-guided.png'), fullPage: true });
    await next.click();
    await expect(page.locator('[data-test="client-next-action"]')).toHaveCount(0);
    const response = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: process.env.JOYMEDIA_UX_PROJECT } });
    expect(response.ok()).toBeTruthy();
    const current = (await response.json()).message;
    const editResponse = await context.request.get('/api/method/joymedia.services.editing.timeline.get_project_timeline', { params: { project_name: process.env.JOYMEDIA_UX_PROJECT, create_if_possible: false } });
    expect(editResponse.ok()).toBeTruthy();
    const edit = (await editResponse.json()).message;
    if(current.production?.is_outdated || edit.is_outdated) {
      await expect(page.getByRole('button', { name: /Export video/ })).toBeVisible();
      await page.locator('[data-test="open-project-history"]').click();
      const history = page.locator('[data-test="project-history"]');
      await history.getByRole('button', { name: 'Exported videos', exact: true }).click();
      await expect(history.getByRole('link', { name: 'Download', exact: true }).first()).toBeVisible();
    } else {
      await expect(page.getByRole('button', { name: /Download video/ })).toBeVisible();
    }
    expect(errors).toEqual([]);
    expect(mutations).toEqual([]);
    if (process.env.JOYMEDIA_UX_SCREENSHOT) await page.screenshot({ path: process.env.JOYMEDIA_UX_SCREENSHOT, fullPage: true });
  });
});

test.describe('live client intake', () => {
  test.skip(!process.env.JOYMEDIA_TEST_SESSION, 'Requires an authorized live session');
  test('create from a brief without optional fields, persist it, then archive the test draft', async ({ page, context }) => {
    const cookies = JSON.parse(await fs.readFile(process.env.JOYMEDIA_TEST_SESSION, 'utf8'));
    await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
    await page.goto('/joymedia/projects');
    await page.getByRole('button', { name: /Create video/ }).first().click();
    await expect(page.locator('[data-test="project-options"]')).toBeVisible();
    await expect(page.locator('[data-test="project-options"]')).not.toHaveAttribute('open');
    const brief = `Client journey integration ${Date.now()}: a short tabletop product film with a final packshot.`;
    await page.getByPlaceholder('Describe the video you want (optional when a workbook is uploaded)').fill(brief);
    const createdResponse = page.waitForResponse(r => r.url().includes('create_project_from_brief') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create project', exact: true }).click();
    const response = await createdResponse;
    expect(response.ok()).toBeTruthy();
    const project = (await response.json()).message.project;
    try {
      await page.waitForURL(`**/projects/${project}`);
      await expect(page.getByRole('button',{name:'Create scene plan',exact:true})).toBeVisible();
      await expect(page.getByRole('textbox',{name:'Video idea',exact:true})).toHaveValue(brief);
      await page.reload();
      await expect(page.getByRole('button',{name:'Create scene plan',exact:true})).toBeVisible();
      await expect(page.getByRole('textbox',{name:'Video idea',exact:true})).toHaveValue(brief);
    } finally {
      const csrf = await page.evaluate(() => window.csrf_token);
      const archived = await context.request.post('/api/method/joymedia.api.projects.archive_project', { headers: { 'X-Frappe-CSRF-Token': csrf }, form: { project_name: project } });
      expect(archived.ok()).toBeTruthy();
      // Reload the genuinely archived draft: entering/leaving it must remain read-only.
      await page.reload();
      await expect(page.locator('[data-test="archived-notice"]')).toBeVisible();
      await expect(page.locator('[data-test="client-next-step"]')).toHaveCount(0);
      await page.getByRole('button', {name:'← Your videos',exact:true}).click();
      await expect(page.locator('[data-test="client-projects"]')).toBeVisible();
      await expect(page.getByText('Restore the project before editing or generating new media.', {exact:false})).toHaveCount(0);
    }
  });
});

test.describe('guided action browser boundaries', () => {
  test.skip(!process.env.JOYMEDIA_TEST_SESSION || !process.env.JOYMEDIA_UX_PROJECT, 'Requires an authorized live session and workspace');
  for (const approved of [false, true]) test(`${approved ? 'prepare missing previews' : 'approve and prepare'} preserves existing frames and never auto-approves them`, async ({ page, context }) => {
    const cookies = JSON.parse(await fs.readFile(process.env.JOYMEDIA_TEST_SESSION, 'utf8'));
    await context.addCookies(Object.entries(cookies).map(([name, value]) => ({ name, value, url: 'http://127.0.0.1:8000' })));
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
    const source = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: process.env.JOYMEDIA_UX_PROJECT } });
    expect(source.ok()).toBeTruthy();
    const workspace = (await source.json()).message;
    workspace.production = null;
    Object.assign(workspace.project, { status: 'Draft', busy_shots: [], current_output_asset_version: '', storyboard_approval_status: approved ? 'Approved' : 'Draft', storyboard_timing_warnings: [], post_production_status: 'Idle' });
    workspace.final_video = null;
    workspace.storyboard.forEach(shot => Object.assign(shot, { selected_output_file: '', output_video: '', selected_output_asset_version: '' }));
    const frames = workspace.storyboard.map((shot, index) => ({ shot: shot.name, needs_keyframe: true, url: index ? '/preview.png' : '', stale: false, status: index ? 'Approved' : 'Pending' }));
    const submitted = [];
    // Only these boundary scenarios replace server responses. No GPU job is submitted.
    await page.route('**/api/method/joymedia.api.projects.get_project_workspace', route => route.fulfill({ json: { message: workspace } }));
    await page.route('**/api/method/joymedia.services.keyframes.stage.get_project_keyframes', route => route.fulfill({ json: { message: frames } }));
    await page.route('**/api/method/joymedia.api.storyboard.approve_project_storyboard', async route => {
      submitted.push('approve');
      workspace.project.storyboard_approval_status = 'Approved';
      await route.fulfill({ json: { message: { approved: true } } });
    });
    await page.route('**/api/method/joymedia.services.keyframes.stage.generate_keyframes', async route => {
      const req = route.request();
      const body = req.headers()['content-type']?.includes('application/json') ? req.postDataJSON() : Object.fromEntries(new URLSearchParams(req.postData()));
      const names = typeof body.shot_names === 'string' ? JSON.parse(body.shot_names) : body.shot_names;
      submitted.push(names);
      await route.fulfill({ json: { message: { status: 'Queued' } } });
    });
    const unsafe = [];
    page.on('request', req => { if (req.method() === 'POST' && /set_keyframe_approval|generate_project_video|approve_scene_brand/.test(req.url())) unsafe.push(req.url()); });
    await page.goto(`/joymedia/projects/${process.env.JOYMEDIA_UX_PROJECT}?editor=advanced`);
    const next = page.locator('[data-test="client-next-action"]');
    await expect(next).toHaveText(approved ? /Prepare previews/ : /Approve Storyboard & prepare previews/);
    await next.click();
    await expect.poll(() => submitted.length).toBe(approved ? 1 : 2);
    expect(submitted).toEqual(approved ? [[frames[0].shot]] : ['approve', [frames[0].shot]]);
    frames[0].url = '/preview.png';
    await page.reload();
    await expect(next).toHaveText(/Review previews below/);
    await next.click();
    expect(unsafe).toEqual([]);
  });
});
