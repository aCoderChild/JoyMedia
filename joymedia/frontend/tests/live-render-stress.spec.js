import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

// Explicit opt-in: these clicks submit actual GPU video jobs. No render route is mocked.
// Keep ordinary CI free of accidental GPU submissions.
const live = process.env.JOYMEDIA_LIVE_RENDER === '1';
const project = process.env.JOYMEDIA_STRESS_PROJECT;
const user = process.env.JOYMEDIA_TEST_USER;
const password = process.env.JOYMEDIA_TEST_PASSWORD;
const output = path.resolve(process.env.JOYMEDIA_STRESS_OUTPUT || 'test-results/live-render');
const method = '/api/method/';
const redoMethod = 'joymedia.services.generation.takes.regenerate_scene';
async function record(event) {
  await fs.mkdir(output, { recursive: true });
  await fs.appendFile(path.join(output, 'events.jsonl'), JSON.stringify({ at: new Date().toISOString(), ...event })+'\n');
}
async function workspace(context) {
  const r = await context.request.get(method+'joymedia.api.projects.get_project_workspace', { params: { name: project } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return (await r.json()).message;
}
async function open(page) {
  page.on('pageerror', error => record({ type: 'pageerror', message: error.message }));
  await page.addInitScript(() => localStorage.setItem('joymedia_lang', 'en'));
  await page.goto(`/joymedia/projects/${project}?editor=advanced`);
  await expect(page.locator('[data-test="storyboard-panel"]')).toHaveCount(7);
}
async function redo(page, index) {
  const received = page.waitForResponse(r => r.url().endsWith(method+redoMethod) && r.request().method()==='POST', { timeout: 120000 });
  await page.locator('[data-test="storyboard-panel"]').nth(index).getByRole('button', { name: '↻ Redo', exact: true }).click();
  const r = await received; const body = await r.json();
  await record({ type:'ui-redo', index, status:r.status(), result:body });
  return { status:r.status(), body };
}
async function waitSelected(context, names, before) {
  let latest;
  await expect.poll(async () => {
    latest = await workspace(context);
    const current = latest.storyboard.filter(s => names.includes(s.name));
    return current.every(s => s.selected_output_asset_version && s.selected_output_asset_version!==before[s.name]) && !names.some(name => latest.project.busy_shots.includes(name));
  }, { timeout: 1200000, intervals:[5000] }).toBeTruthy();
  return latest;
}
async function verifyVideo(context, shot, label) {
  const r = await context.request.get(shot.output_video); expect(r.ok()).toBeTruthy();
  const data=await r.body(); const file=path.join(output, `${label}-${shot.name}-${shot.selected_output_asset_version}.mp4`); await fs.writeFile(file,data);
  const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',file],{encoding:'utf8'}));
  const v=probe.streams.find(s=>s.codec_type==='video');
  expect(Number(v.nb_frames)).toBe(Math.round(Number(shot.duration_seconds)*24));
  expect(v.r_frame_rate).toBe('24/1'); expect(v.width*16).toBe(v.height*9);
  execFileSync('ffmpeg',['-v','error','-i',file,'-map','0:v:0','-f','null','-'],{timeout:120000});
  const evidence={type:'verified-video',label,shot:shot.name,take:shot.selected_output_asset_version,sha256:createHash('sha256').update(data).digest('hex'),bytes:data.length,file,probe};
  await record(evidence); return evidence;
}

test.describe('real Frappe UI to ComfyUI render stress', () => {
  test.describe.configure({ mode: 'serial' });
  test.use({ actionTimeout: 30000 });
  test.skip(!live || !project || !user || !password, 'Explicit real-render opt-in and an isolated project/account are required');
  test.setTimeout(1500000);
  test.beforeEach(async ({context}) => {
    const r=await context.request.post(method+'login',{form:{usr:user,pwd:password}});expect(r.ok()).toBeTruthy();
  });
  test('00 fresh first frames are generated and approved through the UI', async ({page,context}) => {
    await open(page);
    if ((await workspace(context)).project.storyboard_approval_status!=='Approved') {
      const approved=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.api.storyboard.approve_project_storyboard'));
      await page.getByRole('button',{name:/Approve Storyboard/}).click();expect((await approved).ok()).toBeTruthy();
    }
    const existing=await context.request.get(method+'joymedia.services.keyframes.stage.get_project_keyframes',{params:{project_name:project}});
    const currentFrames=(await existing.json()).message;
    if(!currentFrames.every(f=>f.url && !f.stale) && !(await workspace(context)).project.busy_shots.length) {
    const created=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.services.keyframes.stage.generate_keyframes'),{timeout:120000});
    await page.locator('[data-test="draw-all-frames"]').click();
    const submitted=await created;expect(submitted.ok()).toBeTruthy();await record({type:'ui-draw-frames',result:await submitted.json()});
    }
    await expect.poll(async()=>{
      const r=await context.request.get(method+'joymedia.services.keyframes.stage.get_project_keyframes',{params:{project_name:project}});
      expect(r.ok()).toBeTruthy();const frames=(await r.json()).message;
      return frames.length===7 && frames.every(f=>f.url && !f.stale);
    },{timeout:1200000,intervals:[5000]}).toBeTruthy();
    await page.reload();
    await expect(page.locator('[data-test="storyboard-panel"]')).toHaveCount(7);
    for(let i=0;i<7;i++){
      const button=page.locator('[data-test="storyboard-panel"]').nth(i).getByRole('button',{name:'Approve',exact:true});
      if(!await button.count()) continue;
      const approved=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.services.keyframes.stage.set_keyframe_approval'));
      await page.locator('[data-test="storyboard-panel"]').nth(i).getByRole('button',{name:'Approve',exact:true}).click();
      expect((await approved).ok()).toBeTruthy();
    }
    await page.screenshot({path:path.join(output,'fresh-first-frames-approved.png'),fullPage:true});
  });
  test('01 running UI submission can be stopped without replacing its selected take', async ({page,context}) => {
    await open(page);
    if ((await workspace(context)).project.storyboard_approval_status!=='Approved') {
      const approved=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.api.storyboard.approve_project_storyboard'));
      await page.getByRole('button',{name:/Approve Storyboard/}).click();
      expect((await approved).ok()).toBeTruthy();
    }
    const beforeWorkspace=await workspace(context);const before=beforeWorkspace.storyboard[0];
    const submission=await redo(page,0);expect(submission.status).toBe(200);
    const run=submission.body.message.run;let prompt;
    await expect.poll(async()=>{
      const snapshot=JSON.parse(await fs.readFile(path.join(output,'latest-backend.json'),'utf8'));
      const tasks=new Set(snapshot.tasks.filter(t=>t.generation_run===run).map(t=>t.name));
      const running=snapshot.attempts.find(a=>tasks.has(a.generation_task) && a.status==='Running' && a.external_job_id);
      prompt=running?.external_job_id;
      return Boolean(prompt && (snapshot.comfy_queue?.queue_running || []).some(q=>q.prompt===prompt));
    },{timeout:240000,intervals:[2000]}).toBeTruthy();
    await record({type:'confirmed-running-comfy-prompt',run,prompt});
    await page.screenshot({path:path.join(output,'running-before-stop.png'),fullPage:true});
    const stopped=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.api.projects.cancel_project_generation'));
    await page.locator('header').getByRole('button',{name:'Stop',exact:true}).click();
    const r=await stopped;expect(r.ok()).toBeTruthy();const stoppedBody=await r.json();expect(stoppedBody.message.running_tasks).toBe(0);await record({type:'ui-stop',result:stoppedBody});
    await expect.poll(async()=> (await workspace(context)).project.busy_shots.length,{timeout:120000,intervals:[2000]}).toBe(0);
    await expect.poll(async()=>{
      const snapshot=JSON.parse(await fs.readFile(path.join(output,'latest-backend.json'),'utf8'));
      return Boolean(snapshot.comfy_queue) && !Object.values(snapshot.comfy_queue).flat().some(q=>q.prompt===prompt);
    },{timeout:120000,intervals:[2000]}).toBeTruthy();
    const after=await workspace(context);expect(after.storyboard[0].selected_output_asset_version).toBe(before.selected_output_asset_version);
    if(beforeWorkspace.final_video) expect(after.final_video?.asset_version).toBe(beforeWorkspace.final_video.asset_version);
    await page.screenshot({path:path.join(output,'stopped.png'),fullPage:true});
  });
  test('02 two tabs racing the same scene admit exactly one actual render', async ({page,context}) => {
    const raceIndex=Number(process.env.JOYMEDIA_STRESS_RACE_INDEX || 1);
    const target=(await workspace(context)).storyboard[raceIndex].name;
    await expect.poll(async()=>!(await workspace(context)).project.busy_shots.includes(target),{timeout:600000,intervals:[5000]}).toBeTruthy();
    const other=await context.newPage();await Promise.all([open(page),open(other)]);
    const before=await workspace(context);const shot=before.storyboard[raceIndex];
    // A forwarding barrier aligns real HTTP requests; it does not synthesize a response.
    const waiting=[];let release;const gate=new Promise(resolve=>{release=resolve;});
    for (const tab of [page,other]) await tab.route('**/api/method/'+redoMethod,async route=>{
      waiting.push(route);if(waiting.length===2) release();await gate;await route.continue();
    });
    const submissions=await Promise.all([redo(page,raceIndex),redo(other,raceIndex)]);
    for(const tab of [page,other])await tab.unroute('**/api/method/'+redoMethod);
    expect(submissions.filter(s=>s.status===200)).toHaveLength(1);
    expect(submissions.filter(s=>s.status===417 || s.status===409)).toHaveLength(1);
    const after=await waitSelected(context,[shot.name],{[shot.name]:shot.selected_output_asset_version});
    await verifyVideo(context,after.storyboard[raceIndex],'same-scene-race');
    await page.reload();await page.screenshot({path:path.join(output,'race-completed.png'),fullPage:true});
  });
  test('03 three different scenes render concurrently and keep their own outputs',async({page,context})=>{
    const tabs=[page,await context.newPage(),await context.newPage()];await Promise.all(tabs.map(open));
    const before=await workspace(context);const indices=[0,2,4];
    const results=await Promise.all(tabs.map((tab,i)=>redo(tab,indices[i])));expect(results.every(r=>r.status===200)).toBeTruthy();
    await page.screenshot({path:path.join(output,'concurrent-submissions.png'),fullPage:true});
    const shots=indices.map(i=>before.storyboard[i]);const names=shots.map(s=>s.name);
    const after=await waitSelected(context,names,Object.fromEntries(shots.map(s=>[s.name,s.selected_output_asset_version])));
    const evidence=await Promise.all(indices.map(i=>verifyVideo(context,after.storyboard[i],'concurrent')));
    expect(new Set(evidence.map(e=>e.sha256)).size).toBe(3);
  });
  test('04 authored narration is generated through scene menus and placed at exact timings',async({page,context})=>{
    await open(page);
    for(let index=1;index<7;index++){
      const planResponse=await context.request.get(method+'joymedia.services.audio.plan.get_audio_plan',{params:{project_name:project}});
      expect(planResponse.ok()).toBeTruthy();const plan=(await planResponse.json()).message;
      const shot=(await workspace(context)).storyboard[index];
      if(plan.some(c=>c.shot===shot.name && c.role==='Voiceover' && c.scheduled)) continue;
      const panel=page.locator('[data-test="storyboard-panel"]').nth(index);
      await panel.getByTitle('Scene options',{exact:true}).click();
      const generated=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.services.audio.speech.generate_voiceover'),{timeout:180000});
      await panel.locator('[data-test="generate-voiceover"]').click();
      const response=await generated;expect(response.ok(),await response.text()).toBeTruthy();
      await record({type:'ui-narration',shot:shot.name,result:await response.json()});
    }
    const response=await context.request.get(method+'joymedia.services.editing.timeline.get_project_timeline',{params:{project_name:project,create_if_possible:'false'}});
    expect(response.ok()).toBeTruthy();const timeline=(await response.json()).message;
    const voices=timeline.clips.filter(c=>c.enabled && c.audio_role==='Voiceover');
    expect(voices).toHaveLength(6);
    expect(voices.map(c=>c.timeline_start_frame).sort((a,b)=>a-b)).toEqual([96,168,264,384,504,600]);
    await page.screenshot({path:path.join(output,'narration-timeline.png'),fullPage:true});
  });

  test('05 a repeated real take remains distinct and UI export returns a decodable complete film',async({page,context})=>{
    await open(page);const before=await workspace(context);const shot=before.storyboard[0];
    const events=(await fs.readFile(path.join(output,'events.jsonl'),'utf8')).trim().split('\n').map(line=>JSON.parse(line));
    let after;
    if(process.env.JOYMEDIA_STRESS_RESUME_EXPORT==='1'){
      const completed=events.findLast(e=>e.type==='verified-video' && e.label==='repeated-take' && e.shot===shot.name);
      expect(completed?.take).toBe(shot.selected_output_asset_version);
      await record({type:'resume-completed-retake',take:completed.take});after=before;
    }else{
      expect((await redo(page,0)).status).toBe(200);
      after=await waitSelected(context,[shot.name],{[shot.name]:shot.selected_output_asset_version});
    }
    const repeated=await verifyVideo(context,after.storyboard[0],'repeated-take');
    const original=events.find(e=>e.type==='verified-video' && e.label==='concurrent' && e.shot===shot.name);
    expect(repeated.sha256).not.toBe(original?.sha256);
    await expect.poll(async()=> (await workspace(context)).project.post_production_status,{timeout:600000,intervals:[5000]}).toBe('Completed');
    await page.reload();
    await expect(page.locator('[data-test="storyboard-panel"]')).toHaveCount(7);
    await expect(page.locator('header').getByRole('button',{name:/Export video|Download video/})).toBeVisible({timeout:30000});
    const exportButton=page.locator('header').getByRole('button',{name:/Export video/});
    const previousExport=(await workspace(context)).final_video?.asset_version;let submittedExport=false;
    if(await exportButton.count()){
      submittedExport=true;
      const queued=page.waitForResponse(r=>r.request().method()==='POST' && [
        method+'joymedia.services.editing.timeline.queue_project_timeline_export',
        method+'joymedia.services.editing.export_jobs.queue_project_timeline_export'
      ].some(alias=>r.url().endsWith(alias)),{timeout:120000});
      await exportButton.click();const r=await queued;expect(r.ok()).toBeTruthy();await record({type:'ui-export',result:await r.json()});
    }
    let final;
    await expect.poll(async()=>{
      final=await workspace(context);
      const response=await context.request.get(method+'joymedia.services.editing.timeline.get_project_timeline_export_status',{params:{project_name:project}});
      expect(response.ok()).toBeTruthy();const status=(await response.json()).message;
      return status.export_status==='Completed' && Boolean(final.final_video?.file) && (!submittedExport || final.final_video.asset_version!==previousExport);
    },{timeout:600000,intervals:[2000]}).toBeTruthy();
    await page.reload();
    const received=page.waitForEvent('download',{timeout:120000});
    await page.locator('header').getByRole('button',{name:/Download video/}).click();
    const download=await received;expect(await download.failure()).toBeNull();
    await download.saveAs(path.join(output,`ui-downloaded-film-${final.final_video.asset_version}.mp4`));
    await fs.copyFile(path.join(output,`ui-downloaded-film-${final.final_video.asset_version}.mp4`),path.join(output,'ui-downloaded-film.mp4'));
    await record({type:'ui-download',take:final.final_video.asset_version});
    const film=await verifyVideo(context,{name:'complete-film',output_video:final.final_video.file,selected_output_asset_version:final.final_video.asset_version,duration_seconds:30},'export');
    const actual=await fs.readFile(path.join(output,'ui-downloaded-film.mp4'));
    expect(createHash('sha256').update(actual).digest('hex')).toBe(film.sha256);
    expect(final.storyboard).toHaveLength(7);
    await page.reload();await page.screenshot({path:path.join(output,'completed-film.png'),fullPage:true});
  });
  test('06 generated private videos actually play in the Frappe studio',async({page})=>{
    await open(page);
    for(const index of [0,1,2,4,5]){
      const panel=page.locator('[data-test="storyboard-panel"]').nth(index);
      await panel.locator('[data-test="panel-play"]').click();
      const video=panel.locator('[data-test="panel-video"]');
      await expect(video).toBeVisible();
      await expect.poll(async()=>video.evaluate(v=>v.readyState),{timeout:30000,intervals:[100]}).toBeGreaterThanOrEqual(2);
      await video.evaluate(v=>{v.muted=true;return v.play();});
      await expect.poll(async()=>video.evaluate(v=>v.currentTime),{timeout:15000,intervals:[100]}).toBeGreaterThan(.2);
      const playback=await video.evaluate(v=>{v.pause();return {time:v.currentTime,width:v.videoWidth,height:v.videoHeight,duration:v.duration,error:v.error?.message || null};});
      expect(playback.error).toBeNull();expect(playback.width*16).toBe(playback.height*9);
      await record({type:'ui-playback',index,...playback});
    }
    await page.screenshot({path:path.join(output,'real-video-playback.png'),fullPage:true});
  });


  test('07 cancellation stays terminal during delayed refreshes and preserves the exported film',async({page,context})=>{
    await open(page);const before=await workspace(context);
    if(['Queued','Running'].includes(before.production?.status)){
      const stopped=page.waitForResponse(r=>r.url().endsWith(method+'joymedia.api.projects.cancel_project_generation'));
      await page.locator('header').getByRole('button',{name:'Stop',exact:true}).click();
      const response=await stopped;expect(response.ok()).toBeTruthy();const result=await response.json();
      expect(result.message.running_tasks).toBe(0);await record({type:'ui-stop-recovery',result});
    }
    for(let sample=0;sample<18;sample++){
      await page.waitForTimeout(5000);
      if(sample%3===0){await page.reload();await expect(page.locator('[data-test="storyboard-panel"]')).toHaveCount(7);}
      const current=await workspace(context);expect(current.production.status).toBe('Cancelled');
      expect(current.project.busy_shots).toHaveLength(0);
      expect(current.final_video.asset_version).toBe(before.final_video.asset_version);
      await record({type:'cancel-soak',sample,run:current.production.name,status:current.production.status,take:current.final_video.asset_version});
    }
    await page.screenshot({path:path.join(output,'cancelled-retake-preserves-film.png'),fullPage:true});
  });

});
