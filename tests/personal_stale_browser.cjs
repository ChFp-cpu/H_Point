/* Delayed private template responses cannot enter another account or wizard. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable localhost only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:900}}),errors=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const post=async(path,data)=>{const r=await context.request.post(base+path,{data});assert.equal(r.status(),200,await r.text());return r.json()};
 async function delayed(pattern){let ready,release;const seen=new Promise(r=>ready=r),gate=new Promise(r=>release=r);let calls=0;const route=async route=>{if(calls++)return route.continue();const result=await route.fetch();ready();await gate;await route.fulfill({response:result})};await context.route(pattern,route);return{seen,release,remove:()=>context.unroute(pattern,route)}}
 try{
  await emailLogin(page,'theme-browser-data');await post('/api/payments/hp',{item_type:'pro',purchase_key:'personal-stale-pro'});
  await post('/api/personal/templates',{name:'PRIVATE OLD ACCOUNT TEMPLATE',fields:{what:'Private old help',place:'PRIVATE OLD ADDRESS',category:'tech',time_needed:'Tomorrow',urgency:'Normal',details:'PRIVATE DETAILS',expires_in_hours:48,reward_rub:0}});
  await page.evaluate(()=>hpointWorkspace.refresh());await page.goto(base+'/#/help');await page.evaluate(()=>{hpointWorkspace.state.helpTab='mine';hpointWorkspace.refresh()});await page.locator('.personalTools>summary').click();
  const list=await delayed('**/api/personal');await page.locator('[data-personal-action=templates]').click();await list.seen;
  await post('/api/auth/login',{email:'qa905@example.test',password:'SyntheticQa1'});await page.evaluate(()=>{closeModal();return hpointWorkspace.refresh()});
  list.release();await page.waitForTimeout(150);assert.doesNotMatch(await page.locator('#modalbody').innerText(),/PRIVATE OLD/);assert.equal(await page.locator('#modal').isVisible(),false);checks+=2;await list.remove();
  await post('/api/auth/login',{email:'qa901@example.test',password:'SyntheticQa1'});await page.evaluate(()=>hpointWorkspace.refresh());await page.evaluate(()=>{hpointWorkspace.state.helpTab='mine';go('help')});await page.locator('.personalTools>summary').click();await page.locator('[data-personal-action=templates]').click();await page.getByRole('heading',{name:'Шаблоны заявок',exact:true}).waitFor();
  const template=await delayed('**/api/personal/template?*');await page.locator('[data-personal-action=use-template]').click();await template.seen;
  await page.evaluate(()=>{closeModal();requestForm()});await page.locator('#qw').fill('New unsaved request');template.release();await page.waitForTimeout(150);
  assert.equal(await page.locator('#qw').inputValue(),'New unsaved request');assert.equal(await page.evaluate(()=>hpointRequestStep),0);assert.doesNotMatch(await page.locator('#modalbody').innerText(),/PRIVATE OLD ADDRESS/);checks+=3;await template.remove();
  await page.evaluate(()=>closeModal());const created=await post('/api/requests',{what:'PRIVATE TRACKING TITLE',place:'PRIVATE TRACKING ADDRESS',category:'tech',time_needed:'Tomorrow',urgency:'Normal',details:'PRIVATE TRACKING DETAILS'});
  const tracking=await delayed('**/api/requests/tracking?*');await page.evaluate(id=>{openRequestTracking(id)},created.request_id);await tracking.seen;
  await post('/api/auth/login',{email:'qa905@example.test',password:'SyntheticQa1'});await page.evaluate(()=>{closeModal();return hpointWorkspace.refresh()});tracking.release();await page.waitForTimeout(150);
  assert.equal(await page.locator('#modal').isVisible(),false);assert.doesNotMatch(await page.locator('#modalbody').innerText(),/PRIVATE TRACKING/);checks+=2;await tracking.remove();
  assert.deepEqual(errors,[]);checks++;console.log(JSON.stringify({ok:true,checks,accountPrivacy:true,newWizardPreserved:true,trackingPrivacy:true,errors}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
