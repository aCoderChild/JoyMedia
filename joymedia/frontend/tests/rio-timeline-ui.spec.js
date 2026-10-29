import { test, expect } from '@playwright/test';

test('RIO timeline labels edit segments and opens the selected video and audio', async ({ page }) => {
  await page.goto('tests/fixtures/rio-timeline.html');
  const segments = page.locator('.rio-video-clip');
  await expect(segments).toHaveCount(8);
  await expect(segments.first()).toHaveText('Đoạn 1');
  await expect(segments.first()).toHaveAttribute('title', /Cảnh 8/);

  await segments.nth(1).click();
  await expect(page.locator('.rio-monitor video:visible')).toHaveAttribute('src', '/fixture-clip-2.mp4');
  await expect(segments.nth(1)).toHaveClass(/selected/);
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('shot:2');
  await page.getByRole('button', { name: 'Bật/tắt sơ đồ nhỏ' }).click();
  await page.locator('.rio-node-head button[title="Chi tiết cảnh"]').nth(1).click();
  await expect(page.locator('.rio-details')).toContainText('Gấu nhìn hộp giấy');
  await expect(page.locator('.rio-details')).toContainText('Gấu nhìn về phía hộp giấy trên bàn.');
  await expect(page.locator('.rio-details')).toContainText('Sản phẩm');
  await expect(page.locator('.rio-details')).toContainText('Nhân vật');
  await expect(page.locator('.rio-details')).toContainText('Ảnh chưa được tạo');

  await page.getByRole('slider', { name: 'Vị trí xem trước' }).fill('11');
  await expect(page.locator('.rio-monitor video:visible')).toHaveAttribute('src', '/fixture-clip-6.mp4');
  await expect(page.locator('.rio-audio-row')).toHaveCount(2);
  await page.locator('.rio-audio-clip').first().click();
  await page.getByRole('button', { name: 'Tắt', exact: true }).click();
  await expect(page.locator('.rio-audio-clip').first()).toHaveClass(/is-disabled/);
  await page.getByRole('button', { name: 'Bật', exact: true }).click();
  await page.locator('.rio-audio-clip').first().dblclick();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('edit:voice');
  await page.locator('[data-test="rio-add-audio"]').click();
  await page.getByRole('button', { name: 'Chọn tệp âm thanh' }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('add:SFX');
  await page.getByRole('button', { name: 'Xóa khỏi dòng thời gian' }).click();
  expect(await page.evaluate(() => window.fixtureEvents)).toContain('remove:voice');
});
