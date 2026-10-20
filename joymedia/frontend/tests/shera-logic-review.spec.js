import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION,file=process.env.JOYMEDIA_SHERA_REPAIR;
const api='/api/method/';
test.describe('Shera observed logic findings and authored repair',()=>{
 test.skip(!session||!file,'Explicit live case and account required');
 test.setTimeout(120000);
 test('save observed frame findings and four-leg staging without approving or changing footage',async({page,context})=>{
  const data=JSON.parse(await fs.readFile(file,'utf8')),cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
  await page.goto(`/joymedia/projects/${data.project}`);
  await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':await page.evaluate(()=>window.csrf_token)});
  const get=async()=>{const r=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:data.project}});expect(r.ok()).toBeTruthy();return(await r.json()).message;};
  const before=await get(),saved=[];
  for(const finding of (process.env.JOYMEDIA_SHERA_APPLY_ONLY==='1'?[]:data.findings)){
   await page.locator(`[data-test="select-scene-${finding.index}"]`).click();
   const timeline=page.locator('[data-test="client-video"] [data-test="review-timeline"]');await expect(timeline.getByRole('slider')).toBeEnabled();
   await timeline.getByRole('slider').fill(String(finding.frame));await timeline.locator('[data-test="timeline-comment"]').click();
   const dialog=page.locator('[data-test="video-review-dialog"]');await expect(dialog.locator('[data-test="feedback-form"]')).toBeVisible();
   await dialog.getByRole('textbox',{name:'Describe the problem',exact:true}).fill(finding.feedback);
   await dialog.getByText('Problem type & priority (optional)',{exact:true}).click();await dialog.getByLabel('Problem type',{exact:true}).selectOption(finding.category);await dialog.getByLabel('Priority',{exact:true}).selectOption('High');
   const pending=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.review.feedback.add_feedback')&&r.request().method()==='POST');
   await dialog.locator('[data-test="save-video-feedback"]').click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();const row=(await response.json()).message;
   expect(row.asset_version).toBe(before.storyboard[finding.index].selected_output_asset_version);expect(row.start_frame).toBe(finding.frame);saved.push(row);
   await dialog.getByRole('button',{name:'Close review',exact:true}).click();
  }
  if(saved.length)await fs.writeFile('/workspace/development/verification/shera-timeline/observed-findings.json',JSON.stringify(saved,null,2));
  for(const change of data.changes){
   const r=await context.request.post(api+'joymedia.api.storyboard.update_project_shot',{form:{project_name:data.project,shot_name:change.shot,values:JSON.stringify(change.values)}});expect(r.ok(),await r.text()).toBeTruthy();
   expect((await r.json()).message.motion_plan_json).toContain('exactly four corner legs');
  }
  const after=await get();expect(after.storyboard.map(s=>s.selected_output_asset_version)).toEqual(before.storyboard.map(s=>s.selected_output_asset_version));
  expect(after.project.storyboard_approval_status).not.toBe('Approved');expect(after.final_video.asset_version).toBe(before.final_video.asset_version);
  await page.reload();await expect(page.locator('[data-test="client-storyboard"] article')).toHaveCount(7);
  await page.locator('[data-test="client-storyboard"] article').first().getByText('Details',{exact:true}).click();
  await page.locator('[data-test="client-storyboard"] article').first().getByText('Logic & continuity checks',{exact:true}).click();
  await expect(page.locator('[data-test="client-storyboard"] article').first()).toContainText('exactly four corner legs');
  await page.locator('[data-test="client-storyboard"]').screenshot({path:'/workspace/development/verification/shera-timeline/storyboard-logic-requirements.png'});
 });
});
