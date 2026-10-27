import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const session = process.env.JOYMEDIA_TEST_SESSION;
const project = process.env.JOYMEDIA_UX_PROJECT;

test('project and legacy editor links open the JoyMedia studio workspace', async ({ context, page }) => {
  test.skip(!session || !project, 'Authorized live project and session required');
  const cookies = JSON.parse(await fs.readFile(session, 'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name, value]) => ({
    name, value, url: 'http://127.0.0.1:8000',
  })));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'vi'));
  const errors = [];
  const writes = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => {
    if (request.method() === 'POST' && /approve|generate|regenerate|export|update_project/.test(request.url())) {
      writes.push(request.url());
    }
  });
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="rio-studio"]')).toBeVisible();
  await expect(page.locator('[data-test="client-workspace"]')).toHaveCount(0);
  await expect(page.locator('.rio-node').first()).toBeVisible();
  await expect(page.locator('.rio-asset-card').first()).toBeVisible();
  await expect(page.locator('.rio-node textarea').first()).toBeDisabled();
  await expect(page.locator('.rio-asset-card').first()).toHaveAttribute('draggable', 'false');
  await expect(page.locator('.rio-header-actions .rio-classic')).toHaveCount(0);
  await expect(page.locator('.rio-brand')).toContainText('JOYMEDIA');
  await expect(page.locator('.rio-header-link')).toHaveAttribute('href', '/joymedia/projects');
  await page.locator('[data-test="rio-versions-toggle"]').click();
  await expect(page.locator('[data-test="rio-versions"]')).toBeVisible();
  await expect(page.locator('[data-test="video-shelf"]')).toBeVisible();
  await expect(page.locator('[data-test="video-shelf"] [data-video]').first()).toBeVisible();
  await page.getByRole('button', { name: 'Đóng phiên bản' }).click();
  await expect(page.locator('[data-test="rio-versions"]')).toHaveCount(0);
  await page.locator('.rio-asset-size button').first().click();
  await expect(page.locator('.rio-assets-list')).toHaveClass(/size-s/);
  await page.locator('.rio-asset-size button').nth(2).click();
  await expect(page.locator('.rio-assets-list')).toHaveClass(/size-l/);
  await page.locator('.rio-node-preview').first().click();
  await expect(page.locator('.rio-node.active')).toHaveCount(1);
  await page.locator('.rio-asset-image').first().click();
  await expect(page.locator('.rio-details')).toBeVisible();
  const canvasBounds = await page.locator('.rio-canvas').boundingBox();
  const detailsBounds = await page.locator('.rio-details').boundingBox();
  expect(canvasBounds.x + canvasBounds.width).toBeLessThanOrEqual(detailsBounds.x + 1);
  await expect(page.locator('.rio-details-action')).toHaveCount(0);
  await page.locator('.rio-details header button').click();
  await page.locator('.rio-node-head button').first().click();
  await expect(page.locator('.rio-details')).toBeVisible();
  await expect(page.locator('.rio-details-summary span')).toContainText(/^(?:\d+(?:\.\d)?s|—)$/);
  await page.locator('.rio-details header button').click();
  await expect(page.locator('.rio-minimap')).toHaveCount(0);
  await page.locator('.rio-header-actions button[title="Bật/tắt sơ đồ nhỏ"]').click();
  await expect(page.locator('.rio-minimap')).toBeVisible();
  await page.locator('.rio-header-actions button[title="Bật/tắt sơ đồ nhỏ"]').click();
  await expect(page.locator('.rio-minimap')).toHaveCount(0);
  await page.locator('.rio-canvas-controls button').last().click();
  await expect(page.locator('.rio-canvas-controls span')).toContainText('%');
  await page.locator('.rio-asset-plus').click();
  await expect(page.getByRole('heading', { name: 'Thêm tư liệu vào Dự án' })).toBeVisible();
  await page.getByTestId('close-media-picker').click();
  await expect(page.getByTestId('close-media-picker')).toHaveCount(0);
  await page.locator('.rio-header-actions button[title="Cài đặt dự án"]').click();
  await expect(page.locator('[data-test="video-settings-modal"]')).toBeVisible();
  await page.locator('[data-test="video-settings-modal"] button').first().click();
  await page.goto(`/joymedia/projects/${project}?editor=simple`);
  await expect(page).not.toHaveURL(/editor=simple/);
  await expect(page.locator('[data-test="client-workspace"]')).toHaveCount(0);
  await expect(page.locator('[data-test="rio-studio"]')).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
