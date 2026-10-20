import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION,phase=process.env.JOYMEDIA_GENERAL_PHASE;
const output='/workspace/development/verification/case-general',api='/api/method/';
const cases=JSON.parse(await fs.readFile(new URL('../../tests/fixtures/scene_cases.json',import.meta.url),'utf8')).filter(c=>(process.env.JOYMEDIA_GENERAL_CASES||'ceramic_artwork,drinkware').split(',').includes(c.id));
test.describe('shared scene logic for distinct real product inputs',()=>{
 test.skip(!session||!phase,'Explicit authorized case-general verification required');
 test.beforeEach(async({page,context})=>{
  await fs.mkdir(output,{recursive:true});const cookies=JSON.parse(await fs.readFile(session,'utf8'));
  await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
  await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));
 });
 for(const item of cases){
  test(`real input and authored logic: ${item.id}`,async({page,context})=>{
   const errors=[],renders=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/generate_keyframes|generate_project_video|regenerate_scene/.test(r.url()))renders.push(r.url());});
   let project;
   if(phase==='intake'){
    await page.goto('/joymedia/projects');await page.getByRole('button',{name:'+ Create video',exact:true}).click();
    const dialog=page.getByRole('dialog');await dialog.getByPlaceholder('Describe the video you want (optional when a workbook is uploaded)').fill(item.action+' '+item.opening);
    const chooser=page.waitForEvent('filechooser');await dialog.getByRole('button',{name:'+ Add images or a PDF',exact:true}).click();await(await chooser).setFiles('/workspace/development/SAN PHAM AI/'+item.source_file);
    await dialog.getByText('Details',{exact:true}).click();await dialog.getByLabel('Name',{exact:true}).fill(item.label);await dialog.getByLabel('Image type',{exact:true}).click();await page.getByRole('option',{name:'Product',exact:true}).click();
    await dialog.locator('[data-test="project-options"]').getByText('Optional: name & format',{exact:true}).click();await dialog.getByLabel('Project name',{exact:true}).fill('Case-general QA: '+item.label);
    const pending=page.waitForResponse(r=>r.url().endsWith(api+'joymedia.services.intake.project.create_project_from_brief')&&r.request().method()==='POST');await dialog.getByRole('button',{name:'Create project',exact:true}).click();const response=await pending;expect(response.ok(),await response.text()).toBeTruthy();project=(await response.json()).message.project;
    await page.waitForURL(`**/projects/${project}`);await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();
    await fs.appendFile(`${output}/intake.jsonl`,JSON.stringify({id:item.id,project})+'\n');
   }else{
    const fixture=JSON.parse(await fs.readFile(`${output}/authored.json`,'utf8'));const row=fixture.find(r=>r.id===item.id);expect(row).toBeTruthy();project=row.project;
    await page.goto(`/joymedia/projects/${project}`);const scene=page.locator('[data-test="client-storyboard"] article');await expect(scene).toHaveCount(1);
    await scene.getByText('Details',{exact:true}).click();
    await scene.getByText('Logic & continuity checks',{exact:true}).click();
    await expect(scene).toContainText(item.contract.properties[0].value);
    await expect(scene).not.toContainText('corner legs');await expect(scene).not.toContainText('mascot');
    await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':await page.evaluate(()=>window.csrf_token)});
    const before=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:project}});expect(before.ok()).toBeTruthy();const original=(await before.json()).message;
    const invalid=structuredClone(item.contract);invalid.counts[0].count=true;
    const denied=await context.request.post(api+'joymedia.api.storyboard.update_project_shot',{form:{project_name:project,shot_name:row.shot,values:JSON.stringify({motion_plan_json:{scene_contract:invalid}})}});expect(denied.status()).toBe(417);
    const after=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:project}});expect((await after.json()).message.storyboard[0].continuity_checks).toEqual(original.storyboard[0].continuity_checks);
    await scene.screenshot({path:`${output}/${item.id}-storyboard.png`});
   }
   expect(renders).toEqual([]);expect(errors).toEqual([]);
  });
 }
});
