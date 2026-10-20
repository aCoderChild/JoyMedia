import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import {shortCaption,sceneAction,sceneChecks} from '../src/utils/storyboard.js';
const session=process.env.JOYMEDIA_TEST_SESSION;
const output='/workspace/development/verification/storyboard-review';
test('concise captions preserve full source directions and handle long multilingual input',()=>{
 for(const text of ['One vase stands upright. Preserve the decoration.','Gấu ngồi trên ghế. Giữ đúng tỷ lệ.','Một '+ 'chi tiết '.repeat(80),'x'.repeat(500)]){
  const shot={sheet_direction:{action:text}};const before=structuredClone(shot);
  expect(shortCaption(sceneAction(shot)).length).toBeLessThanOrEqual(140);
  expect(shot).toEqual(before);expect(sceneAction(shot)).toBe(text);
 }
 expect(shortCaption('  One vase.\n  Another action. ')).toBe('One vase. Another action.');
 expect(shortCaption('')).toBe('');expect(sceneChecks({motion_plan_json:'malformed'})).toEqual([]);
});
test.describe('real Shera storyboard review',()=>{
 test.skip(!session,'Authorized account required');
 test.beforeEach(async({page,context})=>{
  await fs.mkdir(output,{recursive:true});const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
 });
 test('ordered panels open large, retain full details and navigate without changing production',async({page,context})=>{
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/set_keyframe_approval|generate|set_working_edit|select.*take/.test(r.url()))writes.push(r.url());});
  await page.setViewportSize({width:1440,height:1000});await page.goto('/joymedia/projects/PRJ-02503');
  const board=page.locator('[data-test="storyboard-review"]');await page.locator('[data-test="open-storyboard"]').click();
  const cards=board.locator('article');await expect(cards).toHaveCount(7);await expect(cards.first()).toBeInViewport();
  const grid=board.locator('[data-test="client-storyboard"]');expect(await grid.evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length)).toBe(4);
  await expect(cards.first().locator('.jm-board-details')).not.toHaveAttribute('open','');
  for(const card of await cards.all()){
   expect((await card.locator('[data-test="scene-short-caption"]').textContent()).length).toBeLessThanOrEqual(140);
   await expect(card.locator('img')).toHaveCSS('object-fit','contain');
  }
  await board.screenshot({path:`${output}/shera-board.png`});
  const original=await cards.first().locator('img').getAttribute('src');
  await cards.first().getByRole('button',{name:'Open scene 1',exact:true}).click();
  const dialog=page.locator('[data-test="storyboard-scene-dialog"]');await expect(dialog).toBeVisible();
  await expect(dialog.locator('img')).toHaveAttribute('src',original);
  await dialog.getByText('Details',{exact:true}).click();await expect(dialog).toContainText('exactly four corner legs');
  await dialog.getByRole('button',{name:'Next →',exact:true}).click();await expect(dialog).toContainText('Scene 2 / 7');
  await dialog.getByRole('button',{name:'← Previous',exact:true}).click();await expect(dialog).toContainText('Scene 1 / 7');
  await expect(dialog.getByRole('button',{name:'← Previous',exact:true})).toBeDisabled();
  await page.screenshot({path:`${output}/scene-inspector.png`,fullPage:true});
  await dialog.press('Escape');await expect(dialog).toHaveCount(0);await expect(cards.first().getByRole('button',{name:'Open scene 1',exact:true})).toBeFocused();
  await page.setViewportSize({width:390,height:844});await board.scrollIntoViewIfNeeded();
  expect(await grid.evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length)).toBe(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await cards.first().getByRole('button',{name:'Open scene 1',exact:true}).click();await expect(dialog).toBeVisible();
  await expect(dialog.locator('img')).toHaveCSS('object-fit','contain');
  await page.screenshot({path:`${output}/scene-mobile.png`,fullPage:true});
  await dialog.getByRole('button',{name:'Review video',exact:true}).click();await expect(dialog).toHaveCount(0);await expect(page.locator('[data-test="video-review-dialog"]')).toBeVisible();
  expect(writes).toEqual([]);expect(errors).toEqual([]);
 });
});

test('source-image selection never approves moving action and current intention wins over import',async()=>{
 const {sceneReviewState}=await import('../src/utils/storyboard.js');
 const frame={status:'Approved',url:'/source.png'};
 expect(sceneReviewState({},frame)).toBe('image_selected');
 expect(sceneReviewState({selected_output_asset_version:'take'},frame)).toBe('video_review');
 expect(sceneReviewState({selected_output_asset_version:'take',is_outdated:true},frame)).toBe('outdated');
 expect(sceneAction({authored_action:'Show four connected plies in one sheet.',sheet_direction:{action:'Stack four sheets.'}})).toBe('Show four connected plies in one sheet.');
});
