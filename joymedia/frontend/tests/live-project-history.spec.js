import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const project=process.env.JOYMEDIA_HISTORY_PROJECT;
const output=process.env.JOYMEDIA_HISTORY_OUTPUT;
const session=process.env.JOYMEDIA_TEST_SESSION;
const api='/api/method/';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
test.describe('real project history',()=>{
 test.skip(!project||!output||!session,'Authorized live account and explicit project required');
 test.setTimeout(240000);
 test.beforeEach(async({page,context})=>{
  await fs.mkdir(output,{recursive:true});
  const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
  await page.goto('/joymedia/projects');
  await expect(page.locator(`[data-project="${project}"]`)).toBeVisible();
  const csrf=await page.evaluate(()=>window.csrf_token);
  await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':csrf});
 });
 async function get(context,method,params){const r=await context.request.get(api+method,{params});expect(r.ok(),await r.text()).toBeTruthy();return(await r.json()).message;}
 async function post(context,method,form){const r=await context.request.post(api+method,{form});expect(r.ok(),await r.text()).toBeTruthy();return(await r.json()).message;}
 test('one card exposes retained edits, real exports, scene takes and activity',async({page,context})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const card=page.locator(`[data-project="${project}"]`);
  await expect(page.locator('article[data-project]')).toHaveCount(1);
  await page.goto(`/joymedia/projects/${project}?editor=advanced`);
  await page.locator('[data-test="open-project-history"]').click();
  const dialog=page.locator('[data-test="project-history"]');await expect(dialog).toBeVisible();
  const edits=await get(context,'joymedia.services.project.versions.get_history',{project_name:project});
  await expect(dialog.locator('article[data-edit]')).toHaveCount(edits.items.length);
  await page.screenshot({path:path.join(output,'edits.png'),fullPage:true});
  await dialog.getByRole('button',{name:'Exported videos',exact:true}).click();
  const exports=await get(context,'joymedia.services.project.versions.get_history',{project_name:project,kind:'exports',page_length:100});
  expect(exports.items.length).toBeGreaterThan(1);
  await expect(dialog.getByRole('button',{name:'Preview',exact:true})).toHaveCount(exports.items.length);
  await dialog.getByRole('button',{name:'Preview',exact:true}).first().click();
  const video=dialog.locator('[data-test="history-video"]');
  await expect.poll(()=>video.evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate(v=>{v.muted=true;return v.play();});
  await expect.poll(()=>video.evaluate(v=>v.currentTime)).toBeGreaterThan(.1);
  await video.evaluate(v=>v.pause());
  const downloaded=page.waitForEvent('download');
  await dialog.getByRole('link',{name:'Download',exact:true}).first().click();
  const download=await downloaded;expect(await download.failure()).toBeNull();
  const downloadedPath=path.join(output,'browser-history-export.mp4');await download.saveAs(downloadedPath);
  const files=[];
  for(const entry of exports.items){
   const response=await context.request.get(entry.file);expect(response.ok()).toBeTruthy();
   const bytes=await response.body(),digest=hash(bytes);
   if(entry.content_hash)expect(digest).toBe(entry.content_hash);
   const file=path.join(output,`${entry.name}.mp4`);await fs.writeFile(file,bytes);
   const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-of','json',file],{encoding:'utf8'}));
   execFileSync('ffmpeg',['-v','error','-xerror','-i',file,'-f','null','-'],{timeout:120000});
   files.push({version:entry.name,project:entry.media_project,file:entry.file,sha256:digest,purpose:entry.purpose,probe});
  }
  expect(hash(await fs.readFile(downloadedPath))).toBe(files[0].sha256);
  await fs.writeFile(path.join(output,'verified-export-files.json'),JSON.stringify(files,null,2));
  await page.screenshot({path:path.join(output,'exports.png'),fullPage:true});
  await dialog.getByRole('button',{name:'Scene takes',exact:true}).click();
  await expect(dialog.getByRole('button',{name:'Preview',exact:true}).first()).toBeVisible();
  await expect(dialog.getByRole('button',{name:'Load more',exact:true})).toBeVisible();
  await dialog.getByRole('button',{name:'Load more',exact:true}).click();
  await expect(dialog.getByRole('button',{name:'Preview',exact:true})).toHaveCount(60);
  await dialog.getByRole('button',{name:'Activity',exact:true}).click();
  await expect(dialog.locator('article').first()).toContainText('Generation');
  await page.screenshot({path:path.join(output,'activity.png'),fullPage:true});
  expect(errors).toEqual([]);
 });
 test('new edit preserves source state, submits no jobs, and can be archived without losing history',async({page,context})=>{
  test.skip(process.env.JOYMEDIA_HISTORY_READONLY==='1','Read-only final verification; mutation scenario already exercised');
  const initial=await get(context,'joymedia.services.project.versions.get_history',{project_name:project});
  const working=initial.family.current_edit;
  const before=await get(context,'joymedia.api.projects.get_project_workspace',{name:working});
  let created;
  try{
   await page.goto(`/joymedia/projects/${working}?editor=advanced`);
   await page.locator('[data-test="open-project-history"]').click();
   const dialog=page.locator('[data-test="project-history"]');
   await dialog.getByRole('textbox',{name:'New edit name',exact:true}).fill(`History verification ${Date.now()}`);
   const response=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.project.versions.create_edit')&&r.request().method()==='POST');
   await dialog.getByRole('button',{name:'New edit',exact:true}).click();const r=await response;expect(r.ok(),await r.text()).toBeTruthy();created=(await r.json()).message.edit;
   await page.waitForURL(`**/projects/${created}`);
   await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();
   const current=await get(context,'joymedia.api.projects.get_project_workspace',{name:created});
   expect(current.production).toBeNull();expect(current.final_video).toBeNull();
   expect(current.storyboard.map(s=>Number(s.duration_seconds))).toEqual(before.storyboard.map(s=>Number(s.duration_seconds)));
   expect(current.storyboard.length).toBe(before.storyboard.length);
   await page.locator('[data-test="client-workspace"] header summary').click();
   await page.locator('[data-test="open-advanced-editor"]').click();
   await page.locator('[data-test="open-project-history"]').click();
   const row=page.locator(`[data-edit="${working}"]`);
   const selected=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.project.versions.set_working_edit'));
   await row.getByRole('button',{name:'Set as working edit',exact:true}).click();expect((await selected).ok()).toBeTruthy();
   await expect(row).toContainText('Working edit');
   const archived=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.api.projects.archive_project'));
   await page.locator(`[data-edit="${created}"]`).getByRole('button',{name:'Archive edit',exact:true}).click();expect((await archived).ok()).toBeTruthy();
   await expect(page.locator(`[data-edit="${created}"]`)).toContainText('Archived');
   await fs.writeFile(path.join(output,'created-edit.json'),JSON.stringify({edit:created,working_restored:working,source_shots:before.storyboard.map(s=>s.name),copied_shots:current.storyboard.map(s=>s.name),gpu_jobs:0,archived:true},null,2));
  }finally{
   if(created){
    const state=await get(context,'joymedia.services.project.versions.get_history',{project_name:project});
    if(state.family.current_edit!==working)await post(context,'joymedia.services.project.versions.set_working_edit',{project_name:project,edit_name:working,expected_current:state.family.current_edit});
    await post(context,'joymedia.api.projects.archive_project',{project_name:created});
   }
  }
 });
 test('unauthenticated history access and stale working-edit changes fail safely',async({context})=>{
  const stale=await context.request.post(api+'joymedia.services.project.versions.set_working_edit',{form:{project_name:project,edit_name:project,expected_current:'stale-edit'}});
  expect(stale.status()).toBe(417);
  const anonymous=await context.request.get(api+'joymedia.services.project.versions.get_history',{params:{project_name:project},headers:{Cookie:''}});
  expect([401,403]).toContain(anonymous.status());
 });
});
