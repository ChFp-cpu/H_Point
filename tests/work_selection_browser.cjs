/* Organisation selection and reload preserve the same cabinet and drafts. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable localhost only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 const make=async()=>{const context=await browser.newContext({viewport:{width:390,height:844}});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));return {context,page}};
 const post=async(context,path,data)=>{const response=await context.request.post(base+path,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 try{
  const first=await make(),second=await make();await emailLogin(first.page,'theme-browser-data');await emailLogin(second.page,'theme-browser-empty');
  await post(first.context,'/api/commercial/profile',{kind:'organization',title:'Первая тестовая команда'});
  await post(second.context,'/api/commercial/profile',{kind:'organization',title:'Вторая тестовая команда'});
  const invite=await post(second.context,'/api/commercial/team/invite',{email:'qa901@example.test',role:'admin'});
  await post(first.context,'/api/commercial/team/accept',{invitation_id:invite.result.id});
  await first.page.goto(base+'/#/work/901/tasks');const host=first.page.locator('#commercialWorkspace');await host.locator('[data-commercial-form=tasks]').waitFor();
  await host.locator('[data-commercial-form=tasks] [name=title]').fill('Черновик первой команды');
  await host.locator('[name=commercial_organization]').selectOption('905');await host.getByRole('heading',{name:'Вторая тестовая команда',exact:true}).waitFor();
  await first.page.waitForURL('**/#/work/905/tasks');assert.equal(await host.locator('[name=commercial_organization]').inputValue(),'905');checks+=2;
  assert.equal(await host.locator('[data-commercial-form=tasks] [name=title]').inputValue(),'');checks++;
  await first.page.reload();await host.getByRole('heading',{name:'Вторая тестовая команда',exact:true}).waitFor();assert.equal(await host.locator('[name=commercial_organization]').inputValue(),'905');assert.match(first.page.url(),/work\/905\/tasks$/);checks+=2;
  await host.locator('[name=commercial_organization]').selectOption('901');await host.getByRole('heading',{name:'Первая тестовая команда',exact:true}).waitFor();await first.page.waitForURL('**/#/work/901/tasks');checks++;
  // Drafts are in-memory; inspect their isolation before a document reload.
  await host.locator('[data-commercial-form=tasks] [name=title]').fill('Новый черновик первой команды');await host.locator('[name=commercial_organization]').selectOption('905');await host.getByRole('heading',{name:'Вторая тестовая команда',exact:true}).waitFor();await host.locator('[name=commercial_organization]').selectOption('901');await host.getByRole('heading',{name:'Первая тестовая команда',exact:true}).waitFor();assert.equal(await host.locator('[data-commercial-form=tasks] [name=title]').inputValue(),'Новый черновик первой команды');checks++;
  assert.deepEqual(errors,[]);checks++;console.log(JSON.stringify({ok:true,checks,organizationReload:true,draftIsolation:true,errors}));
 }finally{await Promise.all(contexts.map(c=>c.close()));await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
