import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const file=process.env.JOYMEDIA_ROLE_QA;
const api='/api/method/';
test.describe('explicit account roles',()=>{
 test.skip(!file,'Disposable authorized role accounts required');
 let accounts;
 test.beforeEach(async({page})=>{accounts=JSON.parse(await fs.readFile(file,'utf8'));await page.addInitScript(()=>localStorage.setItem('joymedia_lang','en'));});
 async function login(context,role){const c=accounts[role];const r=await context.request.post(api+'login',{form:{usr:c.user,pwd:c.password}});expect(r.ok()).toBeTruthy();}
 test('client gets guided own-project controls without production or access-management tools',async({page,context})=>{
  await login(context,'client');await page.goto('/joymedia/projects');
  await expect(page.locator('[data-test="account-role"]')).toHaveText('Client');
  await expect(page.getByRole('button',{name:'+ Create video',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Manage reviewers',exact:true})).toHaveCount(0);
  await expect(page.locator('nav a[href="/joymedia/library"]')).toHaveCount(0);
  await page.goto('/joymedia/library');await page.waitForURL('**/joymedia/projects');
  await page.goto(`/joymedia/projects/${accounts.client.project}?editor=advanced`);
  await expect(page.locator('[data-test="client-workspace"]')).toBeVisible();await expect(page).not.toHaveURL(/editor=/);
  await page.locator('[data-test="client-workspace"] header summary').click();
  await expect(page.locator('[data-test="open-advanced-editor"]')).toHaveCount(0);
  await expect(page.locator('[data-test="client-version-history"]')).toBeVisible();
  const hidden=await context.request.get(api+'joymedia.api.projects.get_project_workspace',{params:{name:'PRJ-02503'}});expect([403,417]).toContain(hidden.status());
  const grants=await context.request.get('/api/resource/Partner Access');expect([403,417]).toContain(grants.status());
  await page.screenshot({path:'/workspace/development/verification/flow-ui/client-role.png',fullPage:true});
 });
 test('administrator has an explicit management entry and server capability',async({page,context})=>{
  await login(context,'administrator');await page.goto('/joymedia/projects');
  await expect(page.locator('[data-test="account-role"]')).toHaveText('Administrator');
  await expect(page.getByRole('link',{name:'Manage reviewers',exact:true})).toHaveAttribute('href','/app/partner-access');
  const r=await context.request.get(api+'joymedia.services.partners.get_access');const access=(await r.json()).message;
  expect(access.can_manage_reviewers).toBe(true);expect(access.can_use_advanced_editor).toBe(true);
 });
 test('unassigned account fails closed without a creation interface',async({page,context})=>{
  await login(context,'unassigned');await page.goto('/joymedia/projects');
  await expect(page.locator('[data-test="access-unassigned"]')).toBeVisible();
  await expect(page.getByRole('button',{name:'+ Create video',exact:true})).toHaveCount(0);
  await page.goto('/joymedia/projects/PRJ-02503');await page.waitForURL('**/joymedia/projects');
  await context.setExtraHTTPHeaders({'X-Frappe-CSRF-Token':await page.evaluate(()=>window.csrf_token)});
  const r=await context.request.post(api+'joymedia.api.projects.create_project',{form:{project_name:'Forbidden',product_name:'QA'}});expect([403,417]).toContain(r.status());
 });
 test('production account retains advanced editing without administrator controls',async({page,context})=>{
  await login(context,'production');
  await page.goto('/joymedia/projects');await expect(page.locator('[data-test="account-role"]')).toHaveText('Production team');
  await expect(page.getByRole('link',{name:'Manage reviewers',exact:true})).toHaveCount(0);
  await page.goto(`/joymedia/projects/${accounts.production.project}?editor=advanced`);await expect(page.locator('[data-test="back-to-simple"]')).toBeVisible();
 });
});
