/* Helper preferences are durable, independent of responses and stable while idle. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {openHelpTab}=require('./help_navigation.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket){const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await emailLogin(page,ticket);return {context,page}}
 async function get(a,url){const r=await a.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(a,url,data){const r=await a.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function settings(a){await a.page.goto(base+'/#/help');await a.page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(a.page,'open');await a.page.locator('[data-ws-action="help-tab"][data-tab="preferences"]').first().click();await a.page.locator('#helperPreferencesForm').waitFor()}
 try{
  const helper=await actor('mobile-helper'),author=await actor('theme-browser-data'),page=helper.page;
  const jobs=(await get(author,'/api/sync')).requests,first=jobs.find(r=>r.status==='open').id;
  const next=await post(author,'/api/requests',{what:'Вторая заявка для отклика',place:'Тестовый район',time_needed:'сегодня',urgency:'обычная',category:'tech',details:'Только синтетические данные'});
  await post(helper,'/api/requests/apply',{request_id:first});await post(helper,'/api/requests/apply',{request_id:next.request_id});
  assert.equal((await get(helper,'/api/sync')).my_applications.length,2);checks++;
  await settings(helper);
  assert.equal(await page.locator('.helpNavigation [data-tab="preferences"]').count(),0);
  assert.equal(await page.locator('.helpNavigation').getByText('Я помогаю',{exact:true}).count(),0);checks+=2;
  for(const checkbox of await page.locator('[name="helperCategory"]').all())await checkbox.uncheck();
  await page.locator('#wsHelperCategory_tech').check();await page.locator('#wsHelperCategory_study').check();await page.locator('#wsHelperReady').check();
  await page.locator('.helperAdvanced summary').click();await page.locator('#wsHelperRadius').fill('8');await page.locator('#wsHelperFrom').fill('2030-01-01T10:00');await page.locator('#wsHelperUntil').fill('2030-01-01T20:00');await page.locator('#wsHelperAvailability').fill('После 18:00');
  await page.locator('#wsHelperAvailability').evaluate(e=>{window.qaHelperInput=e;e.focus();e.setSelectionRange(2,7)});
  await page.evaluate(()=>{window.qaHelperForm=document.getElementById('helperPreferencesForm');window.qaHelperMutations=0;window.qaHelperBefore=JSON.stringify(hpointWorkspace.state.data);window.qaHelperRecords=[];window.qaHelperObserver=new MutationObserver(records=>{window.qaHelperMutations+=records.length;window.qaHelperRecords.push(...records.map(r=>({added:[...r.addedNodes].map(n=>n.nodeName+':'+(n.className||n.id||'')),removed:[...r.removedNodes].map(n=>n.nodeName+':'+(n.className||n.id||''))})))}) ;window.qaHelperObserver.observe(document.getElementById('hpointWorkspace'),{childList:true})});
  await page.waitForTimeout(8500);
  if(await page.evaluate(()=>window.qaHelperMutations))console.log('Idle diagnostic',JSON.stringify(await page.evaluate(()=>({records:window.qaHelperRecords,changed:window.qaHelperBefore!==JSON.stringify(hpointWorkspace.state.data)}))));assert.equal(await page.evaluate(()=>window.qaHelperMutations),0,'Idle refresh must not rebuild the workspace');
  assert.equal(await page.locator('#helperPreferencesForm').evaluate(e=>e===window.qaHelperForm),true);
  assert.equal(await page.locator('#wsHelperAvailability').evaluate(e=>e===window.qaHelperInput),true);
  assert.deepEqual(await page.locator('#wsHelperAvailability').evaluate(e=>({focused:document.activeElement===e,start:e.selectionStart,end:e.selectionEnd})),{focused:true,start:2,end:7});
  assert.equal(await page.locator('#wsHelperCategory_tech').isChecked(),true);assert.equal(await page.locator('#wsHelperCategory_study').isChecked(),true);checks+=6;
  const saved=page.waitForResponse(r=>r.url()===base+'/api/helper/preferences'&&r.request().method()==='POST');
  await page.locator('#wsHelperAvailability').press('Enter');assert.equal((await saved).status(),200);
  await page.waitForFunction(()=>hpointWorkspace.state.helperSaving===false);
  let user=(await get(helper,'/api/me')).user;
  assert.deepEqual(user.helper_categories,['tech','study']);assert.equal(user.helper_ready,true);assert.equal(user.helper_radius_km,8);assert.equal(user.helper_availability,'После 18:00');assert.equal((await get(helper,'/api/sync')).my_applications.length,2);checks+=6;
  await page.reload();await page.locator('#hpointWorkspace').waitFor();await settings(helper);
  assert.equal(await page.locator('#wsHelperReady').isChecked(),true);assert.equal(await page.locator('#wsHelperCategory_tech').isChecked(),true);assert.equal(await page.locator('#wsHelperCategory_study').isChecked(),true);checks+=3;
  await page.locator('#wsHelperReady').uncheck();await page.locator('[data-ws-action="helper-preferences-save"]').click();await page.waitForFunction(()=>hpointWorkspace.state.helperSaving===false);
  user=(await get(helper,'/api/me')).user;assert.equal(user.helper_ready,false);assert.deepEqual(user.helper_categories,['tech','study']);assert.equal((await get(helper,'/api/sync')).my_applications.length,2);checks+=3;
  await page.locator('#sitePrimaryNav [data-route="home"]').click();await settings(helper);
  assert.equal(await page.locator('#wsHelperReady').isChecked(),false);assert.equal(await page.locator('#wsHelperCategory_study').isChecked(),true);checks+=2;
  await post(helper,'/api/helper/preferences',{categories:['tools'],availability:'По утрам',ready:false,radius_km:0,available_from:null,available_until:null});
  await page.locator('.helperSettingsHeading h2').click();await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.locator('#wsHelperCategory_tools').isChecked(),true);assert.equal(await page.locator('#wsHelperCategory_tech').isChecked(),false);checks+=2;
  await page.locator('#wsHelperCategory_study').check();await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await page.locator('#wsHelperCategory_study').isChecked(),true);checks++;
  await page.evaluate(()=>window.qaHelperObserver?.disconnect());
  await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'helper-settings-stable.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,preferencesDurable:true,pausedResponsesPreserved:true,enterSubmits:true,idleFormStable:true,checkboxesSynchronized:true}));
 }catch(error){console.error('Helper errors:',errors);throw error}finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
