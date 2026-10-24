/* Actual targeted responses, never production identities or notifications. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844}});contexts.push(context);
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();
  await page.evaluate(()=>Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(ok){ok({coords:{latitude:55.75,longitude:37.61,accuracy:20}})}}}));
  return {context,page};
 }
 const get=async(actor,route)=>actor.context.request.get(base+route).then(response=>response.json());
 async function tab(actor,name){
  await actor.page.goto(base+'/#/help');await actor.page.locator('.helpNavigation [data-tab="'+name+'"]').click();
 }
 async function respond(){
  await tab(helper,'open');
  const card=helper.page.locator('.workspaceRequest').filter({hasText:'#1 ·'});
  await card.getByRole('button',{name:'Хочу помочь',exact:true}).click();
  await helper.page.locator('.sentResponses').waitFor();
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  await author.page.locator('.requestResponses').waitFor();
 }
 let author,helper;
 try{
  author=await login('theme-browser-data');helper=await login('mobile-helper');
  assert.deepEqual((await get(author,'/api/sync')).applications,[],'Generic helper readiness is not a targeted response');checks++;
  for(const colorScheme of ['light','dark']){
   await author.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await author.page.setViewportSize({width,height:844});await tab(author,'mine');
    await author.page.locator('#wsRequestStatus').selectOption('done');
    await author.page.locator('[data-ws-action="request-filter"]').click();
    await tab(author,'open');
    assert.equal(await author.page.locator('#workspaceHistory').count(),0);
    assert.equal(await author.page.locator('#wsRequestStatus').count(),0);
    assert.match(await author.page.locator('.workspaceRequestList').innerText(),/Перенести коробки/);
    await author.page.locator('#wsRequestQuery').fill('Перенести');
    await author.page.locator('[data-ws-action="request-filter"]').click();
    await author.page.evaluate(()=>hpointWorkspace.refresh());
    assert.match(await author.page.locator('.workspaceRequestList').innerText(),/Ожидает помощника/);
    assert.equal(await author.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks+=5;
    await author.page.locator('#wsRequestQuery').fill('');
    await author.page.locator('[data-ws-action="request-filter"]').click();
   }
  }
  await author.page.setViewportSize({width:390,height:844});await tab(author,'mine');
  await author.page.locator('#wsRequestStatus').selectOption('');
  await author.page.locator('[data-ws-action="request-filter"]').click();
  await helper.context.request.post(base+'/api/helper/preferences',{data:{categories:['shopping'],availability:'Вечером',ready:true}});
  await respond();
  const response=(await get(author,'/api/sync')).applications[0];
  assert.equal(response.helper_id,904);assert.equal(response.request_id,1);
  assert.equal((await get(author,'/api/chats')).chats.some(row=>row.request_id===1),false);checks+=2;
  for(const colorScheme of ['light','dark']){
   await author.page.emulateMedia({colorScheme});await helper.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    for(const actor of [author,helper]){
     await actor.page.setViewportSize({width,height:844});await actor.page.evaluate(()=>hpointWorkspace.refresh());
     assert.equal(await actor.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;
    }
   }
  }
  await author.page.locator('.requestResponses summary').click();
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await author.page.locator('.requestResponses').evaluate(node=>node.open),true);checks++;
  await author.page.locator('.requestResponses [data-tab="match"]').click();
  await author.page.locator('.workspaceCandidate').waitFor();
  assert.match(await author.page.locator('.workspaceCandidate').first().innerText(),/Кандидат/);
  assert.match(await author.page.locator('.workspaceCandidate').first().innerText(),/откликнулся на вашу заявку/);checks+=2;
  await helper.page.locator('.sentResponses summary').click();
  await helper.page.locator('.sentResponses [data-ws-action="response-cancel"]').click();
  await helper.page.locator('.sentResponses').waitFor({state:'hidden'});
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await author.page.locator('.requestResponses').count(),0);
  assert.equal(await author.page.locator('.workspaceCandidate [data-user="904"]').count(),0,'Withdrawing clears cached matches and explicit category override');checks+=2;
  await respond();await author.page.locator('.requestResponses summary').click();
  await author.page.locator('.requestResponses [data-ws-action="response-cancel"]').click();
  await author.page.locator('.requestResponses').waitFor({state:'hidden'});
  await helper.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await helper.page.locator('.sentResponses').count(),0);checks++;
  await respond();await author.page.locator('.requestResponses summary').click();
  await author.page.locator('.requestResponses [data-tab="match"]').click();
  await author.page.locator('.workspaceCandidate [data-user="904"]').click();
  await author.page.waitForFunction(()=>hpointWorkspace.state.data.outgoing_offers.length===1);
  const stale=await helper.context.request.post(base+'/api/requests/response/cancel',{data:response});
  assert.equal(stale.status(),409);checks++;
  await helper.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await helper.page.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal((await get(author,'/api/sync')).requests.find(row=>row.id===1).helper_id,904);
  assert.equal(await author.page.locator('.requestResponses').count(),0);
  assert.ok((await get(author,'/api/chats')).chats.some(row=>row.request_id===1));checks+=3;
  await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'responses-confirmed.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,responses:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
