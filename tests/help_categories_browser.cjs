/* Shared directions: real wizard, stored preferences, search and small screens. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const {openHelpTab}=require('./help_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket){const context=await browser.newContext({viewport:{width:390,height:844},colorScheme:'light',reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));await emailLogin(page,ticket);return {context,page}}
 async function get(actor,url){const response=await actor.context.request.get(base+url);assert.equal(response.status(),200,await response.text());return response.json()}
 async function settings(actor){await actor.page.goto(base+'/#/help');await actor.page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(actor.page,'open');await openHelpTab(actor.page,'preferences');await actor.page.locator('#helperPreferencesForm').waitFor()}
 try{
  const author=await actor('theme-browser-data'),helper=await actor('mobile-helper'),page=author.page;
  const catalog=await page.evaluate(()=>hpointHelpCategories.catalog);assert.equal(catalog.length,28);assert.equal(new Set(catalog.map(item=>item.key)).size,28);checks+=2;
  await page.evaluate(()=>requestForm());
  assert.equal(await page.locator('#qc').inputValue(),'');assert.equal(await page.locator('#qc option[value="other"]').count(),1);assert.equal(await page.locator('#qc optgroup').count(),5);checks+=3;
  assert.deepEqual(await page.locator('#qc option').evaluateAll(nodes=>nodes.filter(node=>node.value).map(node=>node.value)),catalog.map(item=>item.key));checks++;
  await page.locator('#qw').fill('Выгулять собаку вечером');await page.locator('#requestNext').click();assert.equal(await page.locator('[data-request-step="0"]').isVisible(),true);assert.match(await page.locator('#rqerr').textContent(),/направление/);checks+=2;
  await page.locator('#qc').selectOption('pets');assert.match(await page.locator('#requestCategoryHint').textContent(),/собак|питом|выгул/i);checks++;
  await page.locator('#requestNext').click();await page.locator('#qp').fill('Тестовый район');await page.evaluate(()=>{window.hpointRequestPoint={lat:55.75,lon:37.62}});await page.locator('#requestNext').click();
  await page.locator('#createRequestButton').click();await page.locator('#modal').waitFor({state:'hidden'});
  let data=await get(author,'/api/sync'),request=data.requests.find(row=>row.what==='Выгулять собаку вечером');assert.ok(request);assert.equal(request.category,'pets');assert.match(request.category_name,/живот|питом/i);checks+=3;
  const second=await author.context.request.post(base+'/api/requests',{data:{what:'Заменить смеситель',place:'Тестовый район',time_needed:'По договорённости',urgency:'Не срочно',details:'Синтетическая заявка',category:'plumbing'}});assert.equal(second.status(),200,await second.text());checks++;
  await settings(helper);
  assert.equal(await helper.page.locator('[name="helperCategory"]').count(),28);assert.equal(await helper.page.locator('.hpHelpCategoryGroup').count(),5);checks+=2;
  await helper.page.locator('#wsHelperCategory_pets').check();await helper.page.locator('#wsHelperCategory_plumbing').check();
  await helper.page.locator('[data-ws-action="helper-preferences-save"]').click();await helper.page.waitForFunction(()=>!hpointWorkspace.state.helperSaving);
  assert.deepEqual((await get(helper,'/api/me')).user.helper_categories,['plumbing','pets']);checks++;
  await helper.page.reload();await helper.page.locator('#hpointWorkspace').waitFor();await settings(helper);assert.equal(await helper.page.locator('#wsHelperCategory_pets').isChecked(),true);assert.equal(await helper.page.locator('#wsHelperCategory_plumbing').isChecked(),true);checks+=2;
  for(const width of [320,390,1440])for(const colorScheme of ['light','dark']){
   await helper.page.setViewportSize({width,height:900});await helper.page.emulateMedia({colorScheme});await helper.page.locator('#helperPreferencesForm').waitFor();
   assert.equal(await helper.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Preferences overflow '+width);checks++;
  }
  await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'help-categories-desktop.png'),fullPage:true});
  await helper.page.setViewportSize({width:390,height:844});await helper.page.emulateMedia({colorScheme:'light'});await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'help-categories-mobile.png'),fullPage:true});
  await helper.page.goto(base+'/#/help');await helper.page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(helper.page,'open');if(!await helper.page.locator('#helpFilters').evaluate(node=>node.open))await helper.page.locator('#helpFilters summary').click();
  await helper.page.locator('#wsRequestCategory').selectOption('pets');await helper.page.locator('#wsRequestQuery').press('Enter');
  assert.equal(await helper.page.locator('#wsRequestCategory').inputValue(),'pets');assert.equal(await helper.page.locator('.workspaceRequest').count(),1);assert.match(await helper.page.locator('.workspaceRequestList').textContent(),/Выгулять собаку/);checks+=3;
  await helper.page.locator('#wsRequestCategory').selectOption('');await helper.page.locator('[data-ws-action="request-filter"]').click();assert.ok(await helper.page.locator('.workspaceRequest').count()>1);checks++;
  await helper.page.locator('#wsRequestCategory').selectOption('pets');await helper.page.locator('#wsRequestQuery').fill('Личный поиск');await helper.page.locator('[data-ws-action="request-filter"]').click();
  const switched=await helper.context.request.post(base+'/api/auth/login',{data:{email:'qa905@example.test',password:'SyntheticQa1'}});assert.equal(switched.status(),200);await helper.page.evaluate(()=>hpointStart());
  assert.deepEqual(await helper.page.evaluate(()=>[hpointWorkspace.state.requestQuery,hpointWorkspace.state.requestCategory,hpointWorkspace.state.requestStatus]),['','','']);assert.equal(await helper.page.locator('#wsRequestQuery').inputValue(),'');assert.equal(await helper.page.locator('#wsRequestCategory').inputValue(),'');checks+=4;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,directions:catalog.length,grouped:true,durablePreferences:true,errors}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
