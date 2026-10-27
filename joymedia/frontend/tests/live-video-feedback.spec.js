import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION;
const project=process.env.JOYMEDIA_CLIENT_EDIT || 'PRJ-02503';
const output=process.env.JOYMEDIA_FEEDBACK_OUTPUT || '/workspace/development/verification/video-feedback';
const api='/api/method/';
test.describe('real version-bound video feedback',()=>{
 test.skip(!session,'Authorized live account required');
 test.beforeEach(async({page,context})=>{
  await fs.mkdir(output,{recursive:true});
  const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
  await page.goto(`/joymedia/projects/${project}`);
  await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();
  await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':await page.evaluate(()=>window.csrf_token)});
 });
 async function get(context,method,params){const r=await context.request.get(api+method,{params});expect(r.ok(),await r.text()).toBeTruthy();return(await r.json()).message;}
 async function evidence(row){await fs.appendFile(`${output}/created-feedback.jsonl`,JSON.stringify(row)+'\n');}
 test('paused-frame area feedback persists in Frappe and a deep link reopens exact evidence',async({page,context})=>{
  const errors=[],jobs=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&/generate_project_video|generate_keyframes|apply_review_comments|queue_project_timeline_export/.test(r.url()))jobs.push(r.url());});
  const before=await get(context,'joymedia.api.projects.get_project_workspace',{name:project});
  await expect(page.locator('[data-test="video-review-dialog"]')).toHaveAttribute('role','region');await expect(page.getByRole('dialog',{name:'Review video',exact:true})).toHaveCount(0);
  const dialog=page.locator('[data-test="video-review-dialog"]');await expect(dialog).toBeVisible();
  const video=dialog.locator('video');await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{v.pause();v.currentTime=2;});
  await dialog.locator('[data-test="review-comment-here"]').click();
  await dialog.getByRole('button',{name:'Mark problem area',exact:true}).click();
  const svg=dialog.locator('[data-test="review-annotation"]');await expect(svg).toHaveAttribute('aria-busy','false');const rect=await svg.boundingBox();
  await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.2);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.55,rect.y+rect.height*.55);await page.mouse.up();
  const text=`Review UI verification ${Date.now()}: check mascot and table proportions in this marked area.`;
  await dialog.getByRole('textbox',{name:'Describe the problem',exact:true}).fill(text);
  await dialog.getByText('Problem type & priority (optional)',{exact:true}).click();
  await dialog.getByLabel('Problem type',{exact:true}).selectOption('Physics');
  const saved=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.review.feedback.add_feedback')&&r.request().method()==='POST');
  await dialog.locator('[data-test="save-video-feedback"]').click();
  const r=await saved;expect(r.ok(),await r.text()).toBeTruthy();const row=(await r.json()).message;await evidence(row);
  expect(row.asset_version).toBe(before.final_video.asset_version);expect(row.category).toBe('Physics');expect(row.owner).toBe('uitest@example.com');
  expect(row.start_frame).toBeGreaterThan(0);expect(row.annotation.x).toBeCloseTo(.2,1);expect(row.annotation.width).toBeCloseTo(.35,1);
  await expect(dialog.locator(`[data-feedback="${row.name}"]`)).toContainText(text);
  const records=await get(context,'joymedia.services.review.feedback.get_feedback',{project_name:project,asset_version:row.asset_version,focused_name:row.name});
  expect(records.focused.feedback).toBe(text);expect(records.focused.annotation).toEqual(row.annotation);
  await page.goto(`/joymedia/projects/${project}?review=${row.asset_version}&feedback=${row.name}`);
  const reopened=page.locator('[data-test="video-review-dialog"]');
  await expect(reopened.locator(`[data-feedback="${row.name}"]`)).toContainText(text);
  await expect.poll(()=>reopened.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await expect.poll(()=>reopened.locator('video').evaluate(v=>v.currentTime)).toBeCloseTo(row.start_seconds,1);
  await expect(reopened.locator('[data-test="review-annotation"] rect')).toBeVisible();
  await page.screenshot({path:`${output}/persisted-area-review.png`,fullPage:true});
  const after=await get(context,'joymedia.api.projects.get_project_workspace',{name:project});
  expect(after.storyboard.map(s=>s.selected_output_asset_version)).toEqual(before.storyboard.map(s=>s.selected_output_asset_version));
  expect(jobs).toEqual([]);expect(errors).toEqual([]);
 });
 test('point tool saves an exact-frame spot and restores it after reload and resize',async({page,context})=>{
  const jobs=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&/generate_project_video|generate_keyframes|queue_project_timeline_export/.test(r.url()))jobs.push(r.url());});
  await expect(page.locator('[data-test="video-review-dialog"]')).toHaveAttribute('role','region');await expect(page.getByRole('dialog',{name:'Review video',exact:true})).toHaveCount(0);
  const dialog=page.locator('[data-test="video-review-dialog"]'),video=dialog.locator('video');
  await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  const frameInput=dialog.getByRole('spinbutton',{name:'Go to frame',exact:true});
  await frameInput.fill('125');await frameInput.press('Tab');
  await expect(frameInput).toHaveValue('125');
  await dialog.getByRole('button',{name:'Next frame',exact:true}).click();await expect(frameInput).toHaveValue('126');
  const surface=dialog.locator('[data-test="review-surface"]');await surface.focus();await surface.press('ArrowLeft');await expect(frameInput).toHaveValue('125');
  await dialog.locator('[data-test="review-point-tool"]').click();
  const overlay=dialog.locator('[data-test="review-annotation"]');await expect(overlay).toHaveAttribute('aria-busy','false');const bounds=await overlay.boundingBox();
  await page.mouse.click(bounds.x+bounds.width*.4,bounds.y+bounds.height*.6);
  await expect(overlay.locator('ellipse')).toBeVisible();
  const text=`Spatial review UI verification ${Date.now()}: exact-frame point on the table geometry.`;
  await dialog.getByRole('textbox',{name:'Describe the problem',exact:true}).fill(text);
  const response=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.review.feedback.add_feedback')&&r.request().method()==='POST');
  await dialog.locator('[data-test="save-video-feedback"]').click();const saved=await response;expect(saved.ok(),await saved.text()).toBeTruthy();
  const row=(await saved.json()).message;await evidence(row);
  expect(row.start_frame).toBe(124);expect(row.end_frame).toBe(124);expect(row.annotation.type).toBe('point');
  expect(row.annotation.x).toBeCloseTo(.4,2);expect(row.annotation.y).toBeCloseTo(.6,2);
  const records=await get(context,'joymedia.services.review.feedback.get_feedback',{project_name:project,asset_version:row.asset_version,focused_name:row.name});expect(records.focused.annotation).toEqual(row.annotation);
  await page.goto(`/joymedia/projects/${project}?review=${row.asset_version}&feedback=${row.name}`);
  await expect(dialog.locator(`[data-feedback="${row.name}"]`)).toContainText('Frame 125');
  await expect(dialog.locator('[data-test="review-annotation"] ellipse')).toBeVisible();
  await expect.poll(()=>video.evaluate(v=>v.currentTime)).toBeCloseTo(124/row.fps,2);
  await expect.poll(()=>video.evaluate(v=>{
   if(v.seeking)return false;const canvas=document.createElement('canvas');canvas.width=canvas.height=16;const ctx=canvas.getContext('2d');ctx.drawImage(v,0,0,16,16);return ctx.getImageData(0,0,16,16).data.some((value,index)=>index%4!==3&&value>30);
  })).toBeTruthy();
  await page.screenshot({path:`${output}/persisted-point-review.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  const mark=dialog.locator('[data-test="review-annotation"] ellipse');await expect(mark).toBeVisible();
  expect(Number(await mark.getAttribute('cx'))).toBeCloseTo(.4,2);expect(Number(await mark.getAttribute('cy'))).toBeCloseTo(.6,2);
  expect(jobs).toEqual([]);expect(errors).toEqual([]);
 });
 test('concurrent retries create one record; another version and anonymous readers see none',async({page,context,playwright})=>{
  const workspace=await get(context,'joymedia.api.projects.get_project_workspace',{name:project});
  const version=workspace.storyboard[0].selected_output_asset_version;
  const names=[];
  for(let round=0;round<3;round++){
    const form={project_name:project,asset_version:version,feedback:`Concurrent review verification ${Date.now()} round ${round}`,request_id:crypto.randomUUID(),start_frame:0,category:'Other'};
    const replies=await Promise.all(Array.from({length:8},()=>context.request.post(api+'joymedia.services.review.feedback.add_feedback',{form})));
    const roundNames=[];for(const r of replies){expect(r.ok(),await r.text()).toBeTruthy();roundNames.push((await r.json()).message.name);}
    expect(new Set(roundNames).size).toBe(1);names.push(roundNames[0]);
    const result=await get(context,'joymedia.services.review.feedback.get_feedback',{project_name:project,asset_version:version,focused_name:roundNames[0]});await evidence(result.focused);
    expect(result.items.filter(i=>i.name===roundNames[0])).toHaveLength(1);
  }
  const other=await get(context,'joymedia.services.review.feedback.get_feedback',{project_name:project,asset_version:workspace.final_video.asset_version,focused_name:names[0]});expect(other.focused).toBeNull();
  const anonymous=await playwright.request.newContext({baseURL:'http://127.0.0.1:8000'});
  const denied=await anonymous.get(api+'joymedia.services.review.feedback.get_feedback',{params:{project_name:project,asset_version:version}});expect([401,403]).toContain(denied.status());await anonymous.dispose();
  const triage=await context.request.post(api+'joymedia.services.review.feedback.triage_feedback',{form:{name:names[0],status:'Resolved',admin_response:'Should be denied'}});
  expect([403,417]).toContain(triage.status());
 });
 test('historical versions offer review without selecting them for production',async({page,context})=>{
  await page.locator('summary', {hasText:/More|Thêm/}).first().click();await page.locator('[data-test="open-project-history"]').click();
  const history=page.locator('[data-test="project-history"]');
  await history.locator('[data-test="history-review"]').last().click();
  const dialog=page.locator('[data-test="video-review-dialog"]');await expect(dialog).toBeVisible();
  await expect.poll(()=>dialog.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await expect(dialog.locator('[data-test="review-comment-here"]')).toBeEnabled();
  await expect(history).toHaveCount(0);await expect(dialog).toHaveAttribute('role','region');
  await expect(page.getByRole('dialog',{name:'Review video',exact:true})).toHaveCount(0);
 });
 test('administrator response is visible on the original immutable review evidence',async({page})=>{
  test.skip(!process.env.JOYMEDIA_ADMIN_REPORT,'Requires completed administrator triage verification');
  const report=JSON.parse(await fs.readFile(process.env.JOYMEDIA_ADMIN_REPORT,'utf8'));
  const row=report.records.find(r=>r.annotation?.type==='point') || report.records.find(r=>r.annotation) || report.records[0];
  await page.goto(`/joymedia/projects/${row.source_edit}?review=${row.asset_version}&feedback=${row.name}`);
  const dialog=page.locator('[data-test="video-review-dialog"]');
  const note=dialog.locator(`[data-feedback="${row.name}"]`);
  await expect(note).toContainText(row.admin_response);
  await expect(note).toContainText('Dismissed');
  await expect.poll(()=>dialog.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  if(row.annotation)await expect(dialog.locator('[data-test="review-annotation"] '+(row.annotation.type==='point'?'ellipse':'rect'))).toBeVisible();
  await page.screenshot({path:`${output}/administrator-response.png`,fullPage:true});
 });

});
