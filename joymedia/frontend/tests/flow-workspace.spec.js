import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION;
const working=process.env.JOYMEDIA_CLIENT_EDIT||'PRJ-02503';
const cardsApi='**/api/method/joymedia.api.projects.get_project_cards';
test.describe('focused media workspace',()=>{
 test.skip(!session,'Authorized live session required');
 test.beforeEach(async({context,page})=>{
  const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
 });
 test('scene selection, retry and review operate on the displayed real video',async({page,context})=>{
  const writes=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&/generate|approve|save_timeline|queue_project/.test(r.url()))writes.push(r.url());});
  const response=await context.request.get('/api/method/joymedia.api.projects.get_project_workspace',{params:{name:working}});
  const snapshot=(await response.json()).message;
  const index=snapshot.storyboard.findIndex(s=>s.selected_output_asset_version&&(s.selected_output_file||s.output_video));expect(index).toBeGreaterThanOrEqual(0);
  const scene=snapshot.storyboard[index];
  await page.goto(`/joymedia/projects/${working}`);
  const video=page.locator('[data-test="client-video"] video');
  await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{window.oldPreview=v;v.muted=true;return v.play();});
  await page.locator(`[data-test="select-scene-${index}"]`).click();
  expect(await page.evaluate(()=>window.oldPreview.paused)).toBeTruthy();
  await expect(video).toHaveAttribute('src',scene.selected_output_file||scene.output_video);
  await expect(page.locator(`[data-test="select-scene-${index}"]`)).toHaveAttribute('aria-pressed','true');
  await video.dispatchEvent('error');
  await page.getByRole('button',{name:'Retry preview',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry preview',exact:true})).toHaveCount(0);
  await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{v.muted=true;return v.play();});
  await page.locator('[data-test="review-full-video"]').click();
  await expect(page.locator('[data-test="video-review-dialog"]')).toBeVisible();
  expect(await video.evaluate(v=>v.paused)).toBeTruthy();
  await expect(page.locator('[data-test="video-review-dialog"] video')).toHaveAttribute('src',scene.selected_output_file||scene.output_video);
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-test="video-review-dialog"]')).toHaveCount(0);
  await page.getByRole('button',{name:'Back to full video',exact:true}).click();
  await expect(page.locator('[data-media-key="master"]')).toHaveAttribute('aria-pressed','true');
  const historyButton=page.locator('[data-test="client-version-history"]');await historyButton.click();
  const history=page.locator('[data-test="project-history"]');await expect(history).toBeFocused();
  await page.keyboard.press('Tab');await expect(history.getByRole('button',{name:'Close history',exact:true})).toBeFocused();
  await page.keyboard.press('Shift+Tab');expect(await history.evaluate(el=>el.contains(document.activeElement))).toBeTruthy();
  await page.keyboard.press('Escape');await expect(historyButton).toBeFocused();
  expect(writes).toEqual([]);expect(errors).toEqual([]);
 });
 test('late searches cannot replace the latest gallery and layout persists',async({page})=>{
  let release;const gate=new Promise(resolve=>release=resolve);
  const slowSeen=new Promise(resolve=>{
   page.route(cardsApi,async route=>{
    const request=route.request();const params=request.method()==='POST'?request.postDataJSON():Object.fromEntries(new URL(request.url()).searchParams);
    if(params.search==='slow'){resolve();await gate;}
    const name=params.search||'initial';await route.fulfill({json:{message:{items:[{name,project_name:name,status:'Draft'}],total:1}}});
   });
  });
  await page.goto('/joymedia/projects');await expect(page.locator('[data-project="initial"]')).toBeVisible();
  const search=page.getByRole('searchbox',{name:'Search videos'});await search.fill('slow');await slowSeen;
  await search.fill('latest');await expect(page.locator('[data-project="latest"]')).toBeVisible();release();
  await page.waitForTimeout(250);await expect(page.locator('[data-project="slow"]')).toHaveCount(0);
  await page.getByRole('button',{name:'List',exact:true}).click();await page.reload();
  await expect(page.getByRole('button',{name:'List',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 });
 test('gallery pagination retains every item without duplication',async({page})=>{
  await page.route(cardsApi,async route=>{
   const request=route.request();const p=request.method()==='POST'?request.postDataJSON():Object.fromEntries(new URL(request.url()).searchParams);
   const start=Number(p.start||0),items=Array.from({length:Math.min(24,49-start)},(_,i)=>({name:`page-${start+i}`,project_name:`Video ${start+i}`,status:'Draft'}));
   await route.fulfill({json:{message:{items,total:49}}});
  });
  await page.goto('/joymedia/projects');await expect(page.locator('[data-project]')).toHaveCount(24);
  await page.getByRole('button',{name:'Load more videos',exact:true}).click();await expect(page.locator('[data-project]')).toHaveCount(48);
  await page.getByRole('button',{name:'Load more videos',exact:true}).click();await expect(page.locator('[data-project]')).toHaveCount(49);
  await expect(page.getByRole('button',{name:'Load more videos',exact:true})).toHaveCount(0);
 });
 test('light mobile workspace supports keyboard scene navigation without overflow',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('joymedia_theme','light'));
  await page.setViewportSize({width:390,height:844});await page.goto(`/joymedia/projects/${working}`);
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  const master=page.locator('[data-media-key="master"]');await master.focus();await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-test="select-scene-0"]')).toBeFocused();
  await expect(page.locator('[data-test="select-scene-0"]')).toHaveAttribute('aria-pressed','true');
  await page.keyboard.press('Home');await expect(master).toBeFocused();await expect(master).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await expect.poll(()=>page.locator('[data-test="client-video"] video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await page.screenshot({path:'/workspace/development/verification/flow-ui/mobile-light.png',fullPage:true});
 });

});
