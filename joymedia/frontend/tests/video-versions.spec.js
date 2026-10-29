import { test, expect } from '@playwright/test';

test('automatic video exposes script and prepared references without submitting work', async ({ page }) => {
  const writes=[];
  page.on('request', request => { if (request.method()==='POST' && /create_product_batch|generate|render_product_variant|retry_product_variant|approve/.test(request.url())) writes.push(request.url()); });
  await page.route('**/api/method/joymedia.api.creative.get_project_batches', route => route.fulfill({ json: { message: [{
    name:'automatic-batch',source_project:'root',delivery_mode:'automatic',status:'Rendering',variants:[{
      index:1,project:'FIXTURE',status:'Keyframes',script:{title:'Visible automatic script',scenes:[{shot_number:1,beat_name:'Hero',action:'Show product',duration_seconds:5}]},
      prepared_assets:[{kind:'Product',status:'supplied',url:'/product.png',description:'front',scenes:[1]}],
    }],
  }] } }));
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.locator('[data-test="rio-script-outputs"]').click();
  const dialog=page.getByRole('dialog',{name:'Kịch bản & đầu ra video'});
  await expect(dialog).toContainText('Visible automatic script');
  await dialog.locator('[data-test="prepared-assets"] summary').click();
  await expect(dialog.locator('[data-test="prepared-assets"] img')).toHaveAttribute('src','/product.png');
  await expect(dialog.locator('[data-test="prepared-assets"]')).toContainText('Ảnh tham chiếu đã cung cấp');
  expect(writes).toEqual([]);
});

test('workspace versions are browse/compare only and experiments stay separate without renumbering', async ({ page }) => {
  let creations = 0;
  page.on('request', request => { if (request.url().includes('create_product_batch')) creations += 1; });
  await page.route('**/api/method/joymedia.api.projects.get_project_videos', route => route.fulfill({ json: { message: { root: 'root', working_edit: 'video-33', videos: [
    { name: 'test-98', number: 98, label: 'Live UI render stress', is_experiment: true, status: 'Needs Attention', is_open: false },
    { name: 'video-33', number: 33, label: 'Final cut', video: '/video-33.mp4', status: 'Completed', is_working_edit: true },
    { name: 'video-14', number: 14, label: 'Camera framing', video: '/video-14.mp4', status: 'Completed' },
  ] } } }));
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.locator('[data-test="rio-versions-toggle"]').click();
  const shelf = page.locator('[data-test="video-shelf"]');
  await expect(shelf.locator('[data-video]')).toHaveCount(2);
  await expect(shelf).toContainText('Video 33');
  await expect(shelf).toContainText('Video 14');
  await expect(shelf.locator('[data-test="generate-from-references"]')).toHaveCount(0);
  await shelf.getByRole('checkbox').nth(0).check();
  await shelf.getByRole('checkbox').nth(1).check();
  await expect(shelf.locator('[data-test="open-compare"]')).toBeVisible();
  await shelf.getByRole('button', { name: /Thử nghiệm/ }).click();
  await expect(shelf.locator('[data-video]')).toHaveCount(1);
  await expect(shelf).toContainText('Video 98');
  await expect(shelf.locator('[data-test="open-compare"]')).toHaveCount(0);
  await shelf.getByRole('button', { name: /^Video ·/ }).click();
  await expect(shelf.locator('[data-video]')).toHaveCount(2);
  expect(creations).toBe(0);
});

test('overview new-video dialog queues only after confirmation and requests script review first', async ({ page }) => {
  let requests = [];
  await page.route('**/api/method/joymedia.api.creative.create_product_batch', async route => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ json: { message: { batch: 'batch-new-video' } } });
  });
  await page.route('**/api/method/joymedia.api.creative.get_product_batch', route => route.fulfill({ json: { message: { status: 'Script Ready', variants: [{ project: 'new-video', status: 'Script Ready' }] } } }));
  await page.goto('tests/fixtures/project-video-dialog.html');
  await expect(page.getByRole('dialog')).toContainText('Bản dựng hiện tại được giữ nguyên');
  expect(requests).toEqual([]);
  await page.getByRole('textbox').fill('A fresh story');
  await page.getByRole('combobox').selectOption('30');
  await page.locator('[data-test="confirm-new-project-video"]').click();
  await expect.poll(() => page.evaluate(() => window.fixtureEvents)).toContain('created:new-video');
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({ source_project: 'root-project', count: 1, direction: 'A fresh story', duration_seconds: 30, auto_render: false, delivery_mode: 'assisted' });
});

test('assisted videos open script review in the workspace without starting rendering', async ({ page }) => {
  let renders = 0;
  page.on('request', request => { if (request.url().includes('render_product_variant')) renders += 1; });
  await page.route('**/api/method/joymedia.api.creative.get_project_batches', route => route.fulfill({ json: { message: [{
    name: 'assisted-batch', source_project: 'root', delivery_mode: 'assisted', status: 'Scripts Ready',
    variants: [{ index: 1, project: 'FIXTURE', status: 'Script Ready', script: { title: 'A new story', scenes: [{ shot_number: 1, beat_name: 'Hero', action: 'Show the product', duration_seconds: 5 }] } }],
  }] } }));
  await page.goto('tests/fixtures/rio-timeline.html');
  const review = page.getByRole('dialog', { name: 'Duyệt video mới' });
  await expect(review).toBeVisible();
  await expect(review).toContainText('A new story');
  await expect(review.getByRole('button', { name: 'Tạo video này', exact: true })).toBeVisible();
  expect(renders).toBe(0);
});
