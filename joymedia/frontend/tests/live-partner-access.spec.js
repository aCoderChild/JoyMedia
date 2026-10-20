import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const privateFile=process.env.JOYMEDIA_PARTNER_SESSION;
const phase=process.env.JOYMEDIA_PARTNER_PHASE || 'review';
const output='/workspace/development/verification/partner-access';
const api='/api/method/';
test.describe('partner role and publication policy',()=>{
 test.skip(!privateFile,'Disposable authorized partner account required');
 let credentials;
 test.beforeEach(async({page,context})=>{
  credentials=JSON.parse(await fs.readFile(privateFile,'utf8'));await fs.mkdir(output,{recursive:true});
  if(phase==='revoked' && credentials.cookies) await context.addCookies(credentials.cookies);
  else {const r=await context.request.post(api+'login',{form:{usr:credentials.user,pwd:credentials.password}});expect(r.ok()).toBeTruthy();}
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
  await page.goto('/joymedia/projects');
  await expect(page.locator('[data-test="partner-home"]')).toBeVisible();
  await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':await page.evaluate(()=>window.csrf_token)});
 });
 async function get(context,method,params){const r=await context.request.get(api+method,{params});expect(r.ok(),await r.text()).toBeTruthy();return(await r.json()).message;}
 test('review-only partner sees the published version, plays it and persists feedback',async({page,context})=>{
  test.skip(phase!=='review');const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await expect(page.locator('[data-test="account-role"]')).toHaveText('Reviewer');
  await expect(page.locator('[data-test="reviewer-access-summary"]')).toContainText('Video creation is disabled');
  const cards=page.locator('[data-published-version]');await expect(cards).toHaveCount(1);
  await expect(cards.first()).toHaveAttribute('data-published-version',credentials.published);
  await expect(page.locator('[data-test="partner-generation"]')).toHaveCount(0);
  await expect(page.getByRole('link',{name:'Download',exact:true})).toHaveCount(0);
  const video=cards.first().locator('video');await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{v.muted=true;return v.play();});await expect.poll(()=>video.evaluate(v=>v.currentTime)).toBeGreaterThan(.1);await video.evaluate(v=>v.pause());
  const range=await context.request.get(api+'joymedia.services.partners.review_media',{params:{asset_version:credentials.published},headers:{Range:'bytes=0-99'}});expect(range.status()).toBe(206);expect((await range.body()).length).toBe(100);
  await cards.first().getByRole('button',{name:'Review & comment',exact:true}).click();
  const dialog=page.locator('[data-test="video-review-dialog"]');await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-test="review-comment-here"]')).toBeEnabled();await dialog.locator('[data-test="review-comment-here"]').click();
  await dialog.getByRole('textbox',{name:'Describe the problem',exact:true}).fill('Partner role integration verification: review product proportions.');
  const saved=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.review.feedback.add_feedback'));
  await dialog.locator('[data-test="save-video-feedback"]').click();const response=await saved;expect(response.ok(),await response.text()).toBeTruthy();const row=(await response.json()).message;
  expect(row.owner).toBe(credentials.user);expect(row.asset_version).toBe(credentials.published);
  await fs.writeFile(`${output}/partner-feedback.json`,JSON.stringify({name:row.name,version:row.asset_version}));
  await expect(dialog.locator(`[data-feedback="${row.name}"]`)).toBeVisible();
  await page.screenshot({path:`${output}/reviewer-feedback.png`,fullPage:true});expect(errors).toEqual([]);
 });
 test('direct URLs, document APIs, hidden video, downloads and generation fail closed',async({page,context})=>{
  test.skip(phase!=='review');
  for(const method of ['joymedia.api.projects.get_project_workspace','joymedia.services.project.versions.get_history']){
   const r=await context.request.get(api+method,{params:{name:credentials.project,project_name:credentials.project}});expect([403,417]).toContain(r.status());
  }
  for(const method of ['joymedia.services.partners.review_media','joymedia.services.review.feedback.get_feedback','joymedia.services.review.timeline.get_review_timeline']){
   const r=await context.request.get(api+method,{params:{asset_version:credentials.hidden,project_name:credentials.project}});expect([403,417]).toContain(r.status());
  }
  const direct=await context.request.get(`/api/resource/Asset Version/${credentials.published}`);expect([403,417]).toContain(direct.status());
  const forbiddenDownload=await context.request.get(api+'joymedia.services.partners.review_media',{params:{asset_version:credentials.published,download:1}});expect([403,417]).toContain(forbiddenDownload.status());
  const create=await context.request.post(api+'joymedia.api.projects.create_project',{form:{project_name:'Forbidden partner project',product_name:'Test',video_idea:'No generation access'}});expect([403,417]).toContain(create.status());
  await page.goto(`/joymedia/projects/${credentials.project}?editor=advanced`);await page.waitForURL('**/joymedia/projects');
  await page.goto('/joymedia/library');await page.waitForURL('**/joymedia/projects');
  await expect(page.locator('[data-test="partner-home"]')).toBeVisible();
 });
 test('administrator enables sandbox creation while private projects remain blocked',async({page,context})=>{
  test.skip(phase!=='generation');
  await expect(page.locator('[data-test="reviewer-access-summary"]')).toContainText('Test creation enabled');
  await expect(page.locator('[data-test="account-role"]')).toHaveText('Reviewer');
  await expect(page.locator('[data-test="partner-generation"]')).toBeVisible();
  await expect(page.getByRole('link',{name:'Download',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'+ Create test video',exact:true}).click();
  await page.getByPlaceholder('Describe the video you want (optional when a workbook is uploaded)').fill('Partner sandbox verification. A short product video with a clear packshot.');
  const pending=page.waitForResponse(r=>r.url().includes('create_project_from_brief')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Create project',exact:true}).click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();const created=(await response.json()).message.project;
  await page.waitForURL(`**/projects/${created}`);await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();
  await expect(page.getByRole('button',{name:'Create scene plan',exact:true})).toBeVisible();
  await page.locator('[data-test="client-workspace"] header summary').click();await expect(page.locator('[data-test="open-advanced-editor"]')).toHaveCount(0);
  const workspace=await get(context,'joymedia.api.projects.get_project_workspace',{name:created});expect(workspace.project.name).toBe(created);
  const more=await Promise.all(Array.from({length:4},()=>context.request.post(api+'joymedia.api.projects.create_project',{form:{project_name:'Over budget',product_name:'Test',video_idea:'Must be rejected'}})));
  for(const r of more)expect([403,417]).toContain(r.status());
  const foreign=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:credentials.project}});expect([403,417]).toContain(foreign.status());
  await fs.writeFile(`${output}/created-project.json`,JSON.stringify({project:created,extra_projects_blocked:4}));
  credentials.cookies=await context.cookies();await fs.writeFile(privateFile,JSON.stringify(credentials),{mode:0o600});
  await page.screenshot({path:`${output}/sandbox.png`,fullPage:true});
 });
 test('revoked publication and feedback permissions affect open sessions',async({page,context})=>{
  test.skip(phase!=='revoked');
  await expect(page.locator('[data-published-version]')).toHaveCount(0);
  const r=await context.request.get(api+'joymedia.services.partners.review_media',{params:{asset_version:credentials.published}});expect([403,417]).toContain(r.status());
  const feedback=await context.request.post(api+'joymedia.services.review.feedback.add_feedback',{form:{project_name:credentials.project,asset_version:credentials.published,feedback:'Blocked',request_id:crypto.randomUUID(),start_frame:0}});expect([403,417]).toContain(feedback.status());
 });
});
