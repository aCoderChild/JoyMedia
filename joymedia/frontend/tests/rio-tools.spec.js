import { test, expect } from '@playwright/test';

test('toolbar edits use the playhead and character/export tools expose real settings', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 850 });
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.getByRole('button', { name: 'Thêm cảnh trống' }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('blank-scene');
  await page.getByRole('button', { name: 'Tư liệu và nhận dạng nhân vật' }).click();
  const characters = page.getByRole('dialog', { name: 'Nhận dạng nhân vật' });
  await characters.getByRole('textbox').fill('SheraBear');
  await characters.getByRole('button', { name: 'Lưu thẻ' }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('identity:bear-version:SheraBear');
  await page.keyboard.press('Escape');
  await expect(characters).toHaveCount(0);
  await page.locator('.rio-video-clip').nth(1).click();
  await page.getByRole('slider', { name: 'Vị trí xem trước' }).fill('3');
  await page.getByRole('button', { name: 'Tách tại đầu phát' }).click();
  await page.getByRole('button', { name: 'Bỏ phần trước đầu phát' }).click();
  await page.getByRole('button', { name: 'Bỏ phần sau đầu phát' }).click();
  const cuts = await page.evaluate(() => window.fixtureToolActions);
  expect(cuts.map(cut => [cut.action, cut.clip.name])).toEqual([['split', 'clip-2'], ['trim', 'clip-2'], ['trim', 'clip-2']]);
  expect(cuts[0].sourceSplitFrame).toBe(24);
  await page.getByRole('button', { name: 'Xóa dòng thời gian', exact: true }).click();
  await page.getByRole('button', { name: 'Hoàn tác chỉnh sửa' }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toEqual(expect.arrayContaining(['clear', 'undo']));
  await page.locator('.rio-export').click();
  const exportDialog = page.getByRole('dialog', { name: 'Xuất video' });
  await exportDialog.getByRole('combobox').selectOption('Studio 1440p60');
  await exportDialog.getByRole('button', { name: 'Xuất video', exact: true }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('export:Studio 1440p60');
});

test('storyboard slicer imports every panel and blocks mismatched replacement', async ({ page }) => {
  let imported;
  await page.route('**/api/method/upload_file', route => route.fulfill({ json: { message: { name: 'uploaded-grid', file_url: '/private/files/grid.png' } } }));
  await page.route('**/api/method/joymedia.services.planning.storyboard_grid.import_grid', async route => {
    imported = route.request().postDataJSON();
    await route.fulfill({ json: { message: { panels: 4, mode: 'append', shots: ['new-1', 'new-2', 'new-3', 'new-4'] } } });
  });
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.getByRole('button', { name: 'Bảng phân cảnh', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Bảng phân cảnh' });
  await dialog.getByRole('button', { name: 'Nhập ảnh dạng lưới' }).click();
  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 101; canvas.height = 103;
    canvas.getContext('2d').fillRect(0, 0, 101, 103);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await dialog.locator('input[type=file]').setInputFiles({ name: 'grid.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64') });
  await dialog.getByLabel('Hàng', { exact: true }).selectOption('2');
  await dialog.getByLabel('Cột', { exact: true }).selectOption('2');
  await dialog.getByRole('button', { name: /Cắt lưới ngay/ }).click();
  await expect(dialog.locator('.slicer-panel-list figure')).toHaveCount(4);
  await dialog.getByLabel('Cách nhập').selectOption('existing');
  await expect(dialog.getByRole('button', { name: /Thay ảnh đầu cảnh/ })).toBeDisabled();
  await dialog.getByLabel('Cách nhập').selectOption('append');
  await dialog.getByRole('button', { name: /Đẩy tất cả cảnh vào canvas/ }).click();
  await expect(dialog.getByRole('button', { name: 'Bảng phân cảnh hiện tại' })).toHaveAttribute('aria-pressed', 'true');
  expect(imported).toMatchObject({ rows: 2, columns: 2, mode: 'append', file_name: 'uploaded-grid' });
  expect(imported.request_id).toBeTruthy();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('storyboard-changed');
});

test('SFX job resumes after closing the panel without re-queueing', async ({ page }) => {
  let queued = 0, checked = 0;
  await page.route('**/api/method/joymedia.api.studio_tools.capabilities', route => route.fulfill({ json: { message: { effects: true } } }));
  await page.route('**/api/method/joymedia.api.studio_tools.queue_effects', async route => {
    queued += 1;
    expect(route.request().postDataJSON()).toMatchObject({ shot_name: 'shot-2', prompt: 'paper rustling' });
    await route.fulfill({ json: { message: { job_id: 'sfx-job' } } });
  });
  await page.route('**/api/method/joymedia.api.studio_tools.effects_status', async route => {
    checked += 1;
    await route.fulfill({ json: { message: { status: checked === 1 ? 'queued' : 'finished' } } });
  });
  await page.goto('tests/fixtures/rio-timeline.html');
  await page.locator('.rio-video-clip').nth(1).click();
  await page.locator('[data-test="rio-add-audio"]').click();
  let dialog = page.getByRole('dialog', { name: 'Hiệu ứng âm thanh' });
  await dialog.getByRole('textbox').fill('paper rustling');
  await dialog.getByRole('button', { name: 'Tạo hiệu ứng', exact: true }).click();
  await expect.poll(() => checked).toBe(1);
  await dialog.getByRole('button', { name: 'Đóng' }).click();
  await page.locator('[data-test="rio-add-audio"]').click();
  dialog = page.getByRole('dialog', { name: 'Hiệu ứng âm thanh' });
  await expect(dialog).toContainText('Đã thêm hiệu ứng vào dòng thời gian.');
  expect(queued).toBe(1);
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('timeline-refresh');
});
