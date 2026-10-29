import { test, expect } from '@playwright/test';

test('opens the current storyboard, keeps local drafts across scene selection, and saves explicitly', async ({ page }) => {
  let saved;
  await page.route('**/api/method/joymedia.services.planning.storyboard_grid.update_scene', async route => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: { message: { title: saved.title, description: saved.description, duration: saved.duration_seconds, continuity: saved.continuity, caption: saved.caption, modified: '2026-10-29 01:00:00' } } });
  });
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.getByRole('button', { name: 'Bảng phân cảnh', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Bảng phân cảnh' });
  await expect(editor.locator('[data-storyboard-scene]')).toHaveCount(8);
  await expect(editor.getByRole('button', { name: 'Bảng phân cảnh hiện tại' })).toHaveAttribute('aria-pressed', 'true');
  await expect(editor.locator('input[type=file]')).toHaveCount(0);
  await editor.getByLabel('Tên cảnh', { exact: true }).fill('Opening');
  await editor.getByLabel('Mô tả cảnh', { exact: true }).fill('A product on the table.');
  await editor.getByLabel('Thời lượng (giây)', { exact: true }).fill('5');
  expect(saved).toBeUndefined();
  await editor.locator('[data-storyboard-scene="shot-2"]').click();
  await editor.locator('[data-storyboard-scene="shot-1"]').click();
  await expect(editor.getByLabel('Tên cảnh', { exact: true })).toHaveValue('Opening');
  await editor.getByRole('button', { name: 'Lưu cảnh', exact: true }).click();
  await expect(editor.getByRole('status')).toContainText('Đã lưu cảnh');
  expect(saved).toMatchObject({ shot_name: 'shot-1', title: 'Opening', description: 'A product on the table.', duration_seconds: 5 });
  await expect(editor.getByRole('button', { name: 'Lưu cảnh', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('storyboard-changed');
});

test('scene-order controls use the selected scene and switching to import does not generate media', async ({ page }) => {
  let reordered, generations = 0;
  page.on('request', request => { if (/generate|render_product_variant|create_product_batch/.test(request.url())) generations += 1; });
  await page.route('**/api/method/joymedia.api.storyboard.reorder_project_shot', async route => {
    reordered = route.request().postDataJSON();
    await route.fulfill({ json: { message: { shot_name: 'shot-2', shot_number: 1 } } });
  });
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.getByRole('button', { name: 'Bảng phân cảnh', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Bảng phân cảnh' });
  await expect(editor.getByRole('button', { name: 'Đưa cảnh lên trước' })).toBeDisabled();
  await editor.locator('[data-storyboard-scene="shot-2"]').click();
  await editor.getByRole('button', { name: 'Đưa cảnh lên trước' }).click();
  await expect.poll(() => reordered).toMatchObject({ project_name: 'FIXTURE', shot_name: 'shot-2', target_shot_number: 1 });
  await editor.getByRole('button', { name: 'Nhập ảnh dạng lưới' }).click();
  await expect(editor.locator('input[type=file]')).toBeVisible();
  await editor.getByRole('button', { name: 'Về bảng phân cảnh' }).click();
  await expect(editor.locator('[data-storyboard-scene]')).toHaveCount(8);
  expect(generations).toBe(0);
});
