/* Mobile help history, filters, preferences and manual location. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs'),{openHelpTab}=require('./help_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),page=await context.newPage(),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());page.on('pageerror',e=>errors.push(e.message));
 try{
  await emailLogin(page,'theme-browser-data');
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:844});await page.emulateMedia({colorScheme});await page.goto(base+'/#/help');await openHelpTab(page,'mine');const history=page.locator('#workspaceHistory');await history.waitFor();if(!await history.evaluate(n=>n.open))await history.locator('summary').click();await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await history.evaluate(n=>n.open),true);await history.locator('summary').click();checks++;
   for(const tab of ['mine','open','match','chats','preferences']){if(tab==='preferences')await openHelpTab(page,'open');await openHelpTab(page,tab);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,width+' '+tab);checks++}
  }
  await page.setViewportSize({width:390,height:844});await openHelpTab(page,'mine');if(!await page.locator('#helpFilters').evaluate(n=>n.open))await page.locator('#helpFilters summary').click();await page.locator('#wsRequestQuery').fill('Совместная');await page.locator('#wsRequestQuery').press('Enter');await page.waitForFunction(()=>hpointWorkspace.state.requestQuery==='Совместная');assert.equal(await page.locator('.workspaceRequest').count(),1);await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await page.locator('#wsRequestQuery').inputValue(),'Совместная');checks+=2;
  await openHelpTab(page,'open');await openHelpTab(page,'preferences');await page.locator('.helperAdvanced summary').click();await page.locator('#wsHelperAvailability').fill('По будням после 18:00');await page.locator('#wsHelperCategory_tech').check();await page.locator('#wsHelperReady').check();await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await page.locator('#wsHelperAvailability').inputValue(),'По будням после 18:00');checks++;
  await page.setViewportSize({width:1440,height:900});await page.waitForFunction(()=>document.querySelectorAll('.helpNavigation>button').length===5);assert.equal(await page.locator('#wsHelperAvailability').inputValue(),'По будням после 18:00');await page.locator('#helperPreferencesForm button[type=submit]').click();await page.waitForFunction(()=>hpointWorkspace.state.data.user.helper_availability==='По будням после 18:00');checks+=2;
  await page.reload();await page.locator('.helpNavigation').waitFor();await openHelpTab(page,'open');await openHelpTab(page,'preferences');const prefs=(await (await context.request.get(base+'/api/me')).json()).user;assert.equal(prefs.helper_ready,true);assert.ok(prefs.helper_categories.includes('tech'));checks+=2;
  await page.evaluate(()=>{window.geoAttempts=0;Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(){geoAttempts++}}});requestForm()});await page.locator('#qw').waitFor();assert.equal(await page.evaluate(()=>geoAttempts),0);await page.locator('#qw').fill('Помочь с домашней техникой');await page.locator('#qc').selectOption('tech');await page.locator('#requestNext').click();await page.locator('#qp').fill('Тестовый город, дом 1');assert.equal(await page.locator('#qp').inputValue(),'Тестовый город, дом 1');assert.equal(await page.evaluate(()=>geoAttempts),0);checks+=3;await page.evaluate(()=>closeModal());
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,mobileHistory:true,filters:true,preferencesStored:true,resizeDrafts:true,noAutomaticGps:true,errors}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
