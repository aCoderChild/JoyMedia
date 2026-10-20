import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION;
const root=process.env.JOYMEDIA_CLIENT_PROJECT || 'PRJ-02501';
const working=process.env.JOYMEDIA_CLIENT_EDIT || 'PRJ-02503';
const output=process.env.JOYMEDIA_CLIENT_OUTPUT || '/tmp/joymedia-client-ui';
const api='/api/method/';
test.describe('simplified client experience',()=>{
 test.skip(!session,'Explicit authorized live session required');
 test.beforeEach(async({context,page})=>{
  await fs.mkdir(output,{recursive:true});
  const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
 });
 test('one concise product card opens a playable real video without write requests',async({page})=>{
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST' && /update_project_brief|initialize|save_timeline|approve|generate|export/.test(r.url()))writes.push(r.url());});
  await page.goto('/joymedia/projects');
  await expect(page.getByRole('heading',{name:'Your videos',exact:true})).toBeVisible();
  const card=page.locator(`[data-project="${root}"]`);await expect(card).toBeVisible();
  await expect(page.getByRole('button',{name:'Needs attention',exact:true})).toHaveCount(0);
  await expect(card.locator('[data-test="card-history"]')).not.toBeVisible();
  await page.screenshot({path:`${output}/projects.png`,fullPage:true});
  await card.getByRole('button',{name:/Open video/}).click();
  await page.waitForURL(`**/projects/${working}`);
  const client=page.locator('[data-test="client-workspace"]');await expect(client).toBeVisible();
  await expect(client.locator('[data-test="client-video"] video')).toBeVisible();
  const v=client.locator('[data-test="client-video"] video');
  await expect.poll(()=>v.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await v.evaluate(v=>{v.muted=true;return v.play();});
  await expect.poll(()=>v.evaluate(v=>v.currentTime)).toBeGreaterThan(.15);
  await v.evaluate(v=>v.pause());
  const downloaded=page.waitForEvent('download');await client.getByRole('link',{name:'Download preview',exact:true}).click();
  expect(await (await downloaded).failure()).toBeNull();
  await expect(page.locator('[data-test="storyboard-panel"]')).toHaveCount(0);
  await page.screenshot({path:`${output}/video.png`,fullPage:true});
  expect(writes).toEqual([]);expect(errors).toEqual([]);
 });
 test('previous videos defaults to saved files; editing tools respect the role',async({page,context})=>{
  await page.goto(`/joymedia/projects/${working}`);
  await page.locator('[data-test="client-workspace"] header summary').click();
  await page.locator('[data-test="open-project-history"]').click();
  const history=page.locator('[data-test="project-history"]');await expect(history).toBeVisible();
  await expect(history.getByRole('button',{name:'Preview',exact:true}).first()).toBeVisible();
  await expect(history.getByRole('button',{name:'New edit',exact:true})).toHaveCount(0);
  await history.getByRole('button',{name:'Close history',exact:true}).click();
  const response=await context.request.get(api+'joymedia.services.partners.get_access');const access=(await response.json()).message;
  if(access.can_use_advanced_editor){
   await page.locator('[data-test="open-advanced-editor"]').click();await page.waitForURL('**/projects/*?editor=advanced');
   await expect(page.locator('[data-test="back-to-simple"]')).toBeVisible();await page.locator('[data-test="back-to-simple"]').click();
  } else {await expect(page.locator('[data-test="open-advanced-editor"]')).toHaveCount(0);}
  await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();
 });
 test('archived video is read-only on entry and on rapid exit',async({page,context})=>{
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  const response=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:working}});expect(response.ok()).toBeTruthy();
  const snapshot=(await response.json()).message;
  snapshot.project.status='Archived';snapshot.family.archived=true;
  await page.route('**/api/method/joymedia.api.projects.get_project_workspace',r=>r.fulfill({json:{message:snapshot}}));
  page.on('request',r=>{if(r.method()==='POST' && /update_project_brief|save_timeline|generate|approve/.test(r.url()))writes.push(r.url());});
  await page.goto(`/joymedia/projects/${working}`);
  await expect(page.locator('[data-test="archived-notice"]')).toBeVisible();
  await expect(page.getByRole('button',{name:'Restore video',exact:true})).toBeVisible();
  await expect(page.locator('[data-test="client-next-step"]')).toHaveCount(0);
  await expect(page.locator('[data-test="review-add"]')).toHaveCount(0);
  await page.getByRole('button',{name:'← Your videos',exact:true}).click();
  await expect(page.locator('[data-test="client-projects"]')).toBeVisible();
  expect(writes).toEqual([]);expect(errors).toEqual([]);
 });
 test('scene images require individual approval and never auto-render',async({page,context})=>{
  const response=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:working}});expect(response.ok()).toBeTruthy();
  const snapshot=(await response.json()).message;
  snapshot.project.storyboard_approval_status='Approved';snapshot.production=null;snapshot.project.busy_shots=[];snapshot.post_production={status:''};snapshot.final_video=null;
  snapshot.storyboard=[{name:'TEST-SCENE',title:'Review proportions',description:'Character sits on a chair beside the table.',is_outdated:false}];
  const frame={shot:'TEST-SCENE',needs_keyframe:true,status:'Pending',stale:false,url:'/assets/joymedia/frontend/assets/Inter.var-C9xDBOS3.woff2'};
  // Reuse the real reference image bytes, with a stable image URL from the real workspace.
  const assets=snapshot.assets||[];
  frame.url=assets.find(a=>/\.(jpg|png|jpeg|webp)(\?|$)/i.test(a.file||a.file_url||''))?.file || assets.find(a=>a.file_url)?.file_url || '/files/preview.png';
  await page.route('**/api/method/joymedia.api.projects.get_project_workspace',r=>r.fulfill({json:{message:snapshot}}));
  await page.route('**/api/method/joymedia.services.keyframes.stage.get_project_keyframes*',r=>r.fulfill({json:{message:[frame]}}));
  const approvals=[],renders=[];
  await page.route('**/api/method/joymedia.services.keyframes.stage.set_keyframe_approval',async r=>{approvals.push(r.request().postData());frame.status='Approved';await r.fulfill({json:{message:{status:'Approved'}}});});
  page.on('request',r=>{if(r.method()==='POST'&&/generate_video|start_generation|generate_keyframes/.test(r.url()))renders.push(r.url());});
  await page.goto(`/joymedia/projects/${working}`);
  await expect(page.getByRole('button',{name:'Use this image',exact:true})).toBeVisible();
  expect(approvals).toHaveLength(0);expect(renders).toHaveLength(0);
  await page.getByRole('button',{name:'Use this image',exact:true}).click();
  await expect(page.getByRole('button',{name:'Generate video',exact:true})).toBeVisible();
  expect(approvals).toHaveLength(1);expect(renders).toHaveLength(0);
 });
 test('mobile view keeps playback and primary actions within the screen',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto(`/joymedia/projects/${working}`);
  await expect(page.locator('[data-test="client-video"] video')).toBeVisible();
  await expect(page.getByRole('link',{name:'Download preview',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.locator('[data-test="client-workspace"] header summary').click();
  await expect(page.getByRole('button',{name:'Video settings',exact:true})).toBeVisible();
  await page.screenshot({path:`${output}/mobile.png`,fullPage:true});
 });

 test('restore handles an archived family and its archived edit in order',async({page,context})=>{
  const response=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:working}});
  expect(response.ok()).toBeTruthy();const snapshot=(await response.json()).message;
  snapshot.project.status='Archived';snapshot.family.archived=true;
  await page.route('**/api/method/joymedia.api.projects.get_project_workspace',r=>r.fulfill({json:{message:snapshot}}));
  const restored=[];
  await page.route('**/api/method/joymedia.api.projects.restore_project',async r=>{
    const req=r.request();const data=req.headers()['content-type']?.includes('application/json')?req.postDataJSON():Object.fromEntries(new URLSearchParams(req.postData()));
    restored.push(data.project_name);
    if(data.project_name===working){snapshot.project.status='Draft';snapshot.family.archived=false;}
    await r.fulfill({json:{message:{restored:true}}});
  });
  await page.goto(`/joymedia/projects/${working}`);
  await page.getByRole('button',{name:'Restore video',exact:true}).click();
  await expect(page.locator('[data-test="archived-notice"]')).toHaveCount(0);
  expect(restored).toEqual([root,working]);
 });

 test('project and per-scene histories play real prior media without changing selection',async({page,context})=>{
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST' && /set_working_edit|select.*take|set_keyframe_approval|approve_scene_brand|generate_project_video|generate_keyframes|queue_project_timeline_export/.test(r.url()))writes.push(r.url());});
  const get=async(method,params)=>{const r=await context.request.get(api+method,{params});expect(r.ok(),await r.text()).toBeTruthy();return(await r.json()).message;};
  const before=await get('joymedia.api.projects.get_project_workspace',{name:working});
  const shot=before.storyboard.find(s=>s.selected_output_file || s.output_video);
  expect(shot).toBeTruthy();
  await page.goto(`/joymedia/projects/${working}`);
  await page.locator('[data-test="client-version-history"]').click();
  const history=page.locator('[data-test="project-history"]');
  await expect(history.getByRole('button',{name:'Full videos',exact:true})).toBeVisible();
  await expect(history.getByRole('button',{name:'Scene versions',exact:true})).toBeVisible();
  await expect(history.getByRole('button',{name:'Preview',exact:true}).first()).toBeVisible();
  await page.screenshot({path:`${output}/full-video-history.png`,fullPage:true});
  await history.getByRole('button',{name:'Close history',exact:true}).click();
  if(!await page.locator(`[data-client-scene="${shot.name}"]`).isVisible())await page.getByText('Request changes to a scene',{exact:true}).click();
  await page.locator(`[data-client-scene="${shot.name}"] [data-test="scene-version-history"]`).click();
  const filter=history.locator('[data-test="history-scene-filter"]');
  await expect(filter).toHaveValue(shot.name);
  const expected=await get('joymedia.services.project.versions.get_history',{project_name:working,kind:'takes',shot_name:shot.name});
  expect(expected.items.length).toBeGreaterThan(0);
  await expect(history.locator('article[data-version]')).toHaveCount(expected.items.length);
  for(const row of expected.items) await expect(history.locator(`[data-version="${row.name}"]`)).toHaveAttribute('data-shot',shot.name);
  await history.getByRole('button',{name:'Preview',exact:true}).first().click();
  const video=history.locator('[data-test="history-video"]');
  await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{v.muted=true;return v.play();});
  await expect.poll(()=>video.evaluate(v=>v.currentTime)).toBeGreaterThan(.1);
  await video.evaluate(v=>v.pause());
  const downloaded=page.waitForEvent('download');await history.getByRole('link',{name:'Download',exact:true}).first().click();
  expect(await(await downloaded).failure()).toBeNull();
  await page.screenshot({path:`${output}/scene-history.png`,fullPage:true});
  await filter.selectOption('');
  const all=await get('joymedia.services.project.versions.get_history',{project_name:working,kind:'takes'});
  await expect(history.locator('article[data-version]')).toHaveCount(all.items.length);
  if(all.has_more){await history.getByRole('button',{name:'Load more',exact:true}).click();await expect(history.locator('article[data-version]')).toHaveCount(60);}
  await filter.selectOption(shot.name);
  await expect(history.locator('article[data-version]')).toHaveCount(expected.items.length);
  // Fast category changes must not let a late scene response replace full-video history.
  await history.getByRole('button',{name:'Full videos',exact:true}).click();
  await history.getByRole('button',{name:'Scene versions',exact:true}).click();
  await history.getByRole('button',{name:'Full videos',exact:true}).click();
  await expect(filter).toHaveCount(0);
  const exports=await get('joymedia.services.project.versions.get_history',{project_name:working,kind:'exports'});
  await expect(history.locator('article[data-version]')).toHaveCount(exports.items.length);
  for(const row of exports.items) await expect(history.locator(`[data-version="${row.name}"]`)).toBeVisible();
  const after=await get('joymedia.api.projects.get_project_workspace',{name:working});
  expect(after.storyboard.map(s=>s.selected_output_asset_version)).toEqual(before.storyboard.map(s=>s.selected_output_asset_version));
  expect(after.family.current_edit).toBe(before.family.current_edit);
  expect(writes).toEqual([]);expect(errors).toEqual([]);
 });

});
