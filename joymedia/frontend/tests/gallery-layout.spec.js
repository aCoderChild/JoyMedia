import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const session=process.env.JOYMEDIA_TEST_SESSION;
test.describe('project gallery sizing',()=>{
 test.skip(!session,'Authorized account required');
 for(const width of [1440,1024,390,320]){
  test(`Vietnamese list and grid do not overlap at ${width}px`,async({page,context})=>{
   const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/archive_project|restore_project|generate|create_project/.test(r.url()))writes.push(r.url());});
   const cookies=JSON.parse(await fs.readFile(session,'utf8'));await context.addCookies(Object.entries(cookies).map(([name,value])=>({name,value,url:'http://127.0.0.1:8000'})));
   await page.addInitScript(()=>{localStorage.setItem('joymedia_lang','vi');localStorage.setItem('joymedia_theme','light');localStorage.setItem('joymedia_project_gallery','list');});
   await page.setViewportSize({width,height:900});await page.goto('/joymedia/projects');
   const card=page.locator('[data-project="PRJ-02501"]');await expect(card).toBeVisible();
   const layout=page.getByRole('group',{name:'Kiểu hiển thị',exact:true});
   for(const mode of ['Danh sách','Lưới']){
    await layout.getByRole('button',{name:mode,exact:true}).click();
    const thumb=await card.locator('.media-thumbnail-root').boundingBox(),copy=await card.locator('.jm-project-copy').boundingBox(),title=await card.locator('h2').boundingBox(),bounds=await card.boundingBox();
    if(mode==='Danh sách')expect(thumb.x+thumb.width).toBeLessThanOrEqual(copy.x+.5);
    else expect(thumb.y+thumb.height).toBeLessThanOrEqual(copy.y+.5);
    expect(title.x).toBeGreaterThanOrEqual(copy.x);expect(title.x+title.width).toBeLessThanOrEqual(bounds.x+bounds.width);
    await expect(card.locator('img')).toHaveCSS('object-fit','contain');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right}))))).toBeTruthy();
    await expect(page.locator('[data-test="role-purpose"]')).toHaveCount(0);
    if(width===1440||width===390){const folder='/workspace/development/verification/gallery-layout';await fs.mkdir(folder,{recursive:true});await page.screenshot({path:`${folder}/${width}-${mode==='Danh sách'?'list':'grid'}.png`,fullPage:true});}
   }
   expect(writes).toEqual([]);expect(errors).toEqual([]);
  });
 }
});
