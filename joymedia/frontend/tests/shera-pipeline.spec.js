import { test, expect } from '@playwright/test';
import path from 'node:path';

// Exercise real authenticated HTTP and Frappe UI. GPU rendering is launched
// separately so rerunning browser checks cannot enqueue duplicate paid work.
const project = process.env.SHERA_TEST_PROJECT;
const user = process.env.JOYMEDIA_TEST_USER;
const password = process.env.JOYMEDIA_TEST_PASSWORD;
const workbook = path.resolve(process.cwd(), '../../../SAN PHAM AI/kich_ban/Shera_TVC_30s_JoyMedia.xlsx');

test.describe('Shera workbook production contract', () => {
  test.skip(!project || !user || !password, 'Set SHERA_TEST_PROJECT and JOYMEDIA_TEST_USER/PASSWORD');

  test.beforeEach(async ({ context, page }) => {
    const response = await context.request.post('/api/method/login', { form: { usr: user, pwd: password } });
    expect(response.ok()).toBeTruthy();
    const loggedIn = await context.request.get('/api/method/frappe.auth.get_logged_user');
    expect((await loggedIn.json()).message).toBe(user);
    await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  });

  test('workbook preview recognizes seven portrait scenes and all reference files', async ({ context }) => {
    const fs = await import('node:fs/promises');
    const uploaded = await context.request.post('/api/method/upload_file', {
      multipart: { is_private: '1', file: { name: path.basename(workbook), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: await fs.readFile(workbook) } },
    });
    expect(uploaded.ok()).toBeTruthy();
    const file = (await uploaded.json()).message;
    const response = await context.request.post('/api/method/joymedia.services.intake.project.preview_workbook', { data: { workbook_file: file.name } });
    expect(response.ok()).toBeTruthy();
    const preview = (await response.json()).message;
    expect(preview.demos).toHaveLength(1);
    expect(preview.demos[0]).toMatchObject({ name: 'TVC 30s', format: 'Portrait', duration_seconds: 30, scene_count: 7, can_create: true, timing_gaps: 0 });
    expect(preview.references.filter(r => !r.drawn).map(r => r.file).sort()).toEqual(['mascot.jpg', 'mascot_front.jpg', 'product.jpg']);
  });

  test('owner can open studio, storyboard and private generated frames', async ({ page, context }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const workspace = await context.request.post('/api/method/joymedia.api.projects.get_project_workspace', { data: { name: project } });
    expect(workspace.ok()).toBeTruthy();
    const data = (await workspace.json()).message;
    expect(data.project.name).toBe(project);
    expect(data.video_settings.duration).toBe(30);
    expect(data.video_settings.delivery_preset).toBe('Portrait');
    await page.goto(`/joymedia/projects/${project}?editor=advanced`);
    await expect(page.locator('header').first()).toBeVisible();
    await expect(page.getByText('Buổi sáng êm đềm', { exact: false }).first()).toBeVisible({ timeout: 20000 });
    await expect(page.locator('[data-test="brand-review"]')).toHaveCount(7);
    const frames = await context.request.get('/api/method/joymedia.services.keyframes.stage.get_project_keyframes', { params: { project_name: project } });
    expect(frames.ok(), await frames.text()).toBeTruthy();
    const rows = (await frames.json()).message;
    expect(rows).toHaveLength(7);
    for (const row of rows.filter(r => r.url)) {
      const image = await context.request.get(row.url);
      expect(image.ok(), `private frame ${row.shot}`).toBeTruthy();
      expect(image.headers()['content-type']).toMatch(/^image\//);
    }
    await page.screenshot({ path: 'test-results/shera-studio.png', fullPage: true });
    expect(errors).toEqual([]);
  });

  test('completed export has seven scenes, six timed voice cues and exactly 720 video frames', async ({ context }) => {
    test.skip(process.env.SHERA_EXPECT_EXPORT !== '1', 'Enable after the real GPU film and finishing jobs complete');
    const response = await context.request.get('/api/method/joymedia.api.projects.get_project_workspace', { params: { name: project } });
    expect(response.ok()).toBeTruthy();
    const workspace = (await response.json()).message;
    expect(workspace.storyboard).toHaveLength(7);
    expect(workspace.storyboard.every(shot => shot.selected_output_asset_version)).toBeTruthy();
    const pendingBrand = workspace.storyboard.filter(shot => shot.brand_review?.required && shot.brand_review.status !== 'Approved');
    expect(workspace.final_video.brand_review_pending_shots.sort()).toEqual(pendingBrand.map(shot => shot.name).sort());
    if (pendingBrand.length) expect(workspace.final_video.brand_review_status).toBe('Needs Review');
    const editResponse = await context.request.get('/api/method/joymedia.services.editing.timeline.get_project_timeline', { params: { project_name: project, create_if_possible: 'false' } });
    expect(editResponse.ok()).toBeTruthy();
    const timeline = (await editResponse.json()).message;
    expect(timeline.total_frames).toBe(720);
    const voices = timeline.clips.filter(clip => clip.enabled && clip.audio_role === 'Voiceover');
    expect(voices.map(clip => clip.timeline_start_frame).sort((a, b) => a - b)).toEqual([96, 168, 264, 384, 504, 600]);
    expect(timeline.clips.some(clip => clip.enabled && clip.audio_role === 'BGM')).toBeTruthy();
    expect(workspace.final_video?.file).toBeTruthy();
    const download = await context.request.get(workspace.final_video.file);
    expect(download.ok()).toBeTruthy();
    const fs = await import('node:fs/promises');
    const { execFileSync } = await import('node:child_process');
    const target = path.resolve('test-results/shera-final-download.mp4');
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, await download.body());
    const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', target], { encoding: 'utf8' }));
    const video = probe.streams.find(stream => stream.codec_type === 'video');
    expect(Number(video.nb_frames)).toBe(720);
    expect(video.r_frame_rate).toBe('24/1');
    expect(video.width * 16).toBe(video.height * 9);
    expect(Number(video.duration)).toBeCloseTo(30, 1);
    expect(probe.streams.some(stream => stream.codec_type === 'audio')).toBeTruthy();
  });
});
