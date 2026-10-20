import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

// Explicit live opt-in. Case data, credentials, and review manifests stay outside code.
const input=process.env.JOYMEDIA_SCENE_CASES,session=process.env.JOYMEDIA_TEST_SESSION;
const phase=process.env.JOYMEDIA_SCENE_PHASE || 'frames',api='/api/method/';
let data,output;
const hash=b=>createHash('sha256').update(b).digest('hex');
async function record(e){await fs.appendFile(path.join(output,'ui-events.jsonl'),JSON.stringify({at:new Date().toISOString(),...e})+'\n');}
async function get(context,method,params){const r=await context.request.get(api+method,{params,maxRetries:2});expect(r.ok()).toBeTruthy();return(await r.json()).message;}
const frames=c=>get(c,'joymedia.services.keyframes.stage.get_project_keyframes',{project_name:data.project});
const workspace=c=>get(c,'joymedia.api.projects.get_project_workspace',{name:data.project});
async function click(page,button,method){await expect(button).toBeEnabled({timeout:30000});const pending=page.waitForResponse(r=>r.url().endsWith(api+method)&&r.request().method()==='POST',{timeout:120000});await button.click();const r=await pending;expect(r.ok(),await r.text()).toBeTruthy();return r.json();}
test.describe('actual scene-contract jobs',()=>{
 test.use({actionTimeout:30000});
 test.skip(process.env.JOYMEDIA_LIVE_RENDER!=='1'||!input||!session,'Explicit live scenario and session required');
 test.setTimeout(2400000);
 test.beforeEach(async({page,context})=>{
  data=JSON.parse(await fs.readFile(input,'utf8'));output=path.dirname(input);
  const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
  await page.goto(`/joymedia/projects/${data.project}?editor=advanced`);
  await expect(page.locator('[data-test="storyboard-panel"]').first()).toBeVisible();
  const csrf=await page.evaluate(()=>window.csrf_token);
  if(csrf) await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':csrf});
 });
 test('reject malformed contracts without creating jobs',async({context})=>{
  test.skip(phase!=='validation');
  const before=await workspace(context),shot=data.cases[0].shot;
  const invalid=[
   {scene_contract:{version:true}},
   {scene_contract:{version:1,entities:[{id:'x',label:'subject'}],relations:[{kind:'attached_to',subject:'x',object:'missing'}]}},
   {scene_contract:{version:1,events:[{id:'event',description:'event',start:true,end:1}]}},
   {scene_contract:{version:1,entities:[{id:'a',label:'a'},{id:'b',label:'b'}],relations:[{kind:'attached_to',subject:'a',object:'b'},{kind:'attached_to',subject:'b',object:'a'}]}},
  ];
  for(const plan of invalid){
   const r=await context.request.post(api+'joymedia.api.storyboard.update_project_shot',{form:{project_name:data.project,shot_name:shot,values:JSON.stringify({motion_plan_json:plan})}});
   expect(r.status()).toBe(417);await record({type:'invalid-contract',status:r.status(),response:await r.json()});
  }
  const after=await workspace(context);
  expect(after.storyboard.find(s=>s.name===shot).motion_plan_json).toBe(before.storyboard.find(s=>s.name===shot).motion_plan_json);
  expect(after.project.busy_shots).toEqual(before.project.busy_shots);
 });
 test('draw staged frames',async({page,context})=>{
  test.skip(phase!=='frames');
  const approve=page.getByRole('button',{name:/Approve Storyboard/});
  if(await approve.count()) await click(page,approve,'joymedia.api.storyboard.approve_project_storyboard');
  for(const c of data.cases){
   const existing=(await frames(context)).find(f=>f.shot===c.shot);
   if(existing?.url && !existing.stale && !c.redraw) continue;
   await record({type:'draw-click',shot:c.shot});
   const result=await click(page,page.locator('[data-test="storyboard-panel"]').nth(c.index).getByRole('button',{name:/^(Draw|Redraw)$/,exact:true}),'joymedia.services.keyframes.stage.generate_keyframes');
   await record({type:'draw',shot:c.shot,result});
   await expect.poll(async()=>!(await workspace(context)).project.busy_shots.includes(c.shot),{timeout:1200000,intervals:[5000]}).toBeTruthy();
   await page.reload();
  }
  await expect.poll(async()=>{
   const current=await frames(context);return data.cases.every(c=>current.some(f=>f.shot===c.shot&&f.url&&!f.stale));
  },{timeout:1800000,intervals:[5000]}).toBeTruthy();
  await fs.writeFile(path.join(output,'frames.json'),JSON.stringify(await frames(context),null,2));
  await page.reload();await page.screenshot({path:path.join(output,'staged-first-frames.png'),fullPage:true});
 });
 test('approve inspected frames and render motion',async({page,context})=>{
  test.skip(!['render','verify'].includes(phase));
  const approveStory=page.getByRole('button',{name:/Approve Storyboard/});
  if(await approveStory.count()) await click(page,approveStory,'joymedia.api.storyboard.approve_project_storyboard');
  const reviewed=JSON.parse(await fs.readFile(path.join(output,'reviewed-frames.json'),'utf8'));
  const current=await frames(context);
  for(const c of data.cases){
   const f=current.find(f=>f.shot===c.shot);expect(f?.stale).toBeFalsy();
   const image=await context.request.get(f.url);expect(image.ok()).toBeTruthy();expect(hash(await image.body())).toBe(reviewed[c.shot]);
   const approve=page.locator('[data-test="storyboard-panel"]').nth(c.index).getByRole('button',{name:'Approve',exact:true});
   if(await approve.count()) await click(page,approve,'joymedia.services.keyframes.stage.set_keyframe_approval');
  }
  const before=phase==='verify'?JSON.parse(await fs.readFile(path.join(output,'render-before.json'),'utf8')):await workspace(context);
  if(phase!=='verify') await fs.writeFile(path.join(output,'render-before.json'),JSON.stringify(before));
  for(const c of phase==='verify'?[]:data.cases){
   const result=await click(page,page.locator('[data-test="storyboard-panel"]').nth(c.index).getByRole('button',{name:'↻ Redo',exact:true}),'joymedia.services.generation.takes.regenerate_scene');
   await record({type:'render',shot:c.shot,result});
  }
  let result;
  await expect.poll(async()=>{
   result=await workspace(context);return data.cases.every(c=>{
    const s=result.storyboard.find(s=>s.name===c.shot),old=before.storyboard.find(s=>s.name===c.shot);
    return s.selected_output_asset_version!==old.selected_output_asset_version&&!result.project.busy_shots.includes(c.shot);
   });
  },{timeout:2100000,intervals:[5000]}).toBeTruthy();
  for(const c of data.cases){
   const s=result.storyboard.find(s=>s.name===c.shot),r=await context.request.get(s.output_video);expect(r.ok()).toBeTruthy();
   const bytes=await r.body(),file=path.join(output,`${s.name}-${s.selected_output_asset_version}.mp4`);await fs.writeFile(file,bytes);
   const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-of','json',file],{encoding:'utf8'}));
   expect(Number(probe.streams.find(s=>s.codec_type==='video').nb_frames)).toBe(Math.round(c.duration*(c.fps||data.fps||24)));
   execFileSync('ffmpeg',['-v','error','-xerror','-i',file,'-f','null','-'],{timeout:120000});
   await record({type:'verified',shot:s.name,take:s.selected_output_asset_version,file,sha256:hash(bytes),probe});
  }
  await page.screenshot({path:path.join(output,'constrained-motion-completed.png'),fullPage:true});
 });
 test('export and download the complete edited film',async({page,context})=>{
  test.skip(phase!=='export');
  const before=await workspace(context);
  await page.getByRole('button',{name:'Timeline / Edit',exact:true}).click();
  const exportButton=page.locator('header').getByRole('button',{name:/Export video/});await expect(exportButton).toBeVisible({timeout:30000});
  const response=page.waitForResponse(r=>r.request().method()==='POST' && ['joymedia.services.editing.timeline.queue_project_timeline_export','joymedia.services.editing.export_jobs.queue_project_timeline_export'].some(m=>r.url().endsWith(api+m)),{timeout:120000});
  await exportButton.click();const queued=await response;expect(queued.ok()).toBeTruthy();await record({type:'export',result:await queued.json()});
  let final;
  await expect.poll(async()=>{
   final=await workspace(context);const state=await get(context,'joymedia.services.editing.timeline.get_project_timeline_export_status',{project_name:data.project});
   return state.export_status==='Completed'&&final.final_video?.asset_version&&final.final_video.asset_version!==before.final_video?.asset_version;
  },{timeout:600000,intervals:[2000]}).toBeTruthy();
  await page.reload();const received=page.waitForEvent('download',{timeout:120000});
  await page.locator('header').getByRole('button',{name:/Download video/}).click();const download=await received;expect(await download.failure()).toBeNull();
  const file=path.join(output,`complete-film-${final.final_video.asset_version}.mp4`);await download.saveAs(file);
  const request=await context.request.get(final.final_video.file);expect(request.ok()).toBeTruthy();expect(hash(await request.body())).toBe(hash(await fs.readFile(file)));
  const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',file],{encoding:'utf8'}));
  const timeline=await get(context,'joymedia.services.editing.timeline.get_project_timeline',{project_name:data.project});
  expect(Number(probe.streams.find(s=>s.codec_type==='video').nb_frames)).toBe(timeline.total_frames);
  execFileSync('ffmpeg',['-v','error','-xerror','-i',file,'-f','null','-'],{timeout:120000});
  await record({type:'verified-export',take:final.final_video.asset_version,file,sha256:hash(await fs.readFile(file)),probe,timeline});
  await page.screenshot({path:path.join(output,'complete-film.png'),fullPage:true});
 });

 test('select the reviewed take through the studio',async({page,context})=>{
  test.skip(phase!=='select');
  for(const c of data.cases){
   if(!c.approved_take) continue;
   for(let step=0;step<20;step++){
    const current=await workspace(context),shot=current.storyboard.find(s=>s.name===c.shot);
    if(shot.selected_output_asset_version===c.approved_take) break;
    const response=await click(page,page.locator('[data-test="storyboard-panel"]').nth(c.index).getByTitle('Previous take',{exact:true}),'joymedia.services.generation.takes.select_scene_take');
    await record({type:'select-reviewed-take',shot:c.shot,expected:c.approved_take,result:response});
    await expect.poll(async()=> (await workspace(context)).storyboard.find(s=>s.name===c.shot).take_index,{timeout:30000}).toBe(shot.take_index-1);
   }
   expect((await workspace(context)).storyboard.find(s=>s.name===c.shot).selected_output_asset_version).toBe(c.approved_take);
  }
  await page.reload();await page.screenshot({path:path.join(output,'reviewed-takes-selected.png'),fullPage:true});
 });

 test('reuse reviewed music and fit it to the film',async({page,context})=>{
  test.skip(phase!=='music');
  await page.getByRole('button',{name:'Timeline / Edit',exact:true}).click();
  const current=await get(context,'joymedia.services.editing.timeline.get_project_timeline',{project_name:data.project});
  if(!current.clips.some(c=>c.enabled&&c.audio_role==='BGM'&&c.source_asset_version===data.music_asset_version)){
  await page.getByRole('button',{name:/Add audio track/}).click();
  await page.getByPlaceholder('Search by name...').fill(data.music_asset_name);
  await page.locator('.media-candidate-card').filter({hasText:data.music_asset_name}).click();
  const added=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.editing.timeline.add_timeline_audio_clip'));
  await page.getByTestId('confirm-add-reference').click();expect((await added).ok()).toBeTruthy();
  }
  await page.locator('.audio-timeline-clip').filter({hasText:data.music_asset_name}).dblclick();
  await click(page,page.getByRole('button',{name:'Fit BGM to Full Video',exact:true}),'joymedia.services.editing.timeline.fit_audio_clip_to_full_video');
  const gain=page.locator('input[type="range"][min="-24"]');
  const updated=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.editing.timeline.update_timeline_clip_audio'));
  await gain.evaluate(el=>{el.value='-12';el.dispatchEvent(new Event('change',{bubbles:true}));});expect((await updated).ok()).toBeTruthy();
  const timeline=await get(context,'joymedia.services.editing.timeline.get_project_timeline',{project_name:data.project});
  const music=timeline.clips.find(c=>c.audio_role==='BGM'&&c.enabled);
  expect(music.source_asset_version).toBe(data.music_asset_version);expect(music.source_out_frame-music.source_in_frame).toBe(Math.max(...timeline.clips.filter(c=>c.track_type==='Video'&&c.enabled).map(c=>c.timeline_end_frame)));expect(music.gain_db).toBe(-12);
  await record({type:'reviewed-music',music});await page.screenshot({path:path.join(output,'reviewed-music-timeline.png'),fullPage:true});
 });

 test('reviewed private videos play in the studio',async({page})=>{
  test.skip(phase!=='playback');
  for(const c of data.cases){
   const panel=page.locator('[data-test="storyboard-panel"]').nth(c.index);await panel.locator('[data-test="panel-play"]').click();
   const video=panel.locator('[data-test="panel-video"]');await expect(video).toBeVisible();
   await expect.poll(()=>video.evaluate(v=>v.readyState),{timeout:30000,intervals:[100]}).toBeGreaterThanOrEqual(2);
   await video.evaluate(v=>{v.muted=true;return v.play();});
   await expect.poll(()=>video.evaluate(v=>v.currentTime),{timeout:15000,intervals:[100]}).toBeGreaterThan(.2);
   const playback=await video.evaluate(v=>{v.pause();return {time:v.currentTime,width:v.videoWidth,height:v.videoHeight,duration:v.duration,error:v.error?.message||null};});
   expect(playback.error).toBeNull();await record({type:'playback',shot:c.shot,...playback});
  }
  await page.screenshot({path:path.join(output,'reviewed-takes-playback.png'),fullPage:true});
 });

});
