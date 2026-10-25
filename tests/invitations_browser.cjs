const {openHelpTab}=require('./help_navigation.cjs');
/* Real two-sided invitation flows against the disposable local QA database. */
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
  return {context,page};
 }
 async function get(actor,route){const response=await actor.context.request.get(base+route);assert.equal(response.status(),200);return response.json()}
 async function post(actor,route,data){const response=await actor.context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 async function outgoing(){return (await get(author,'/api/sync')).outgoing_offers}
 async function invite(helper){return post(author,'/api/smart-match/assign',{request_id:1,helper_id:helper})}
 async function match(){
  await author.page.goto(base+'/#/help');await author.page.locator('.helpNavigation').waitFor();
  await openHelpTab(author.page,'match');
  await author.page.locator('[data-ws-action="match-load"]').waitFor({state:'visible'});
  await author.page.waitForFunction(()=>hpointWorkspace.state.matchLoading===false);
 }
 let author,helper,other;
 try{
  author=await login('theme-browser-data');helper=await login('mobile-helper');other=await login('theme-browser-empty');
  await post(other,'/api/helper/preferences',{categories:['tech'],availability:'Днём',ready:true});
  for(const colorScheme of ['light','dark']){
   await author.page.emulateMedia({colorScheme});await helper.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await author.page.setViewportSize({width,height:844});
    await invite(904);let offer=(await outgoing())[0];
    await match();
    await author.page.locator('.workspaceAppNotice.workspacePendingInvite').waitFor();
    await author.page.locator('.workspaceCandidate [data-user="905"]').waitFor();
    assert.equal(await author.page.locator('.workspaceCandidate [data-user="904"]').count(),0);
    assert.equal(await author.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Invitation and long replacement label fit the screen');checks++;
    if(width===390)await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`invitations-${colorScheme}-${width}.png`),fullPage:true});
    await author.page.locator('.workspaceAppNotice [data-ws-action="offer-cancel"]').click();
    await author.page.locator('.workspaceAppNotice.workspacePendingInvite').waitFor({state:'hidden'});
    assert.deepEqual(await outgoing(),[]);assert.deepEqual((await get(helper,'/api/helper/offers')).offers,[]);
    const stale=await helper.context.request.post(base+'/api/helper/offers/respond',{data:{request_id:1,accept:true,offer_token:offer.offer_token}});
    assert.equal(stale.status(),409);
    assert.equal((await get(author,'/api/sync')).requests.find(row=>row.id===1).status,'open');checks++;
    await invite(904);offer=(await outgoing())[0];
    await author.page.locator('[data-ws-action="match-load"]').click();
    await author.page.locator('.workspaceAppNotice.workspacePendingInvite').waitFor();
    await helper.page.goto(base+'/#/home');await helper.page.locator('.workspaceOfferNotice').waitFor();
    assert.equal(await helper.page.locator('[data-ws-action="offer"][data-accept="false"]').innerText(),'Отклонить');
    await helper.page.locator('[data-ws-action="offer"][data-accept="false"]').click();
    await helper.page.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
    await author.page.evaluate(()=>hpointWorkspace.refresh());
    assert.equal(await author.page.locator('.workspaceAppNotice.workspacePendingInvite').count(),0,'Live sync removes a cancelled invitation, even with cached matches');
    assert.deepEqual(await outgoing(),[]);checks++;
    await author.page.locator('[data-ws-action="match-load"]').click();
    await author.page.locator('.workspaceCandidate [data-user="905"]').waitFor();
    assert.equal(await author.page.locator('.workspaceCandidate [data-user="904"]').count(),0,'A declined helper is not repeatedly suggested for this request');checks++;
   }
  }
  // The folded notice on the home page also offers cancellation and matching.
  await invite(904);await author.page.goto(base+'/#/home');
  await author.page.locator('.outgoingOffers summary').click();
  assert.equal(await author.page.getByRole('button',{name:'Подобрать другого',exact:true}).count(),1);
  await author.page.locator('.outgoingOffers [data-ws-action="offer-cancel"]').click();
  await author.page.locator('.outgoingOffers').waitFor({state:'hidden'});assert.deepEqual(await outgoing(),[]);checks++;
  // No replacement is implicit: dismissing the confirmation sends nothing.
  await invite(904);let old=(await outgoing())[0];await match();
  let assignments=0;author.page.on('request',r=>{if(r.url().endsWith('/api/smart-match/assign'))assignments++});
  author.page.once('dialog',dialog=>dialog.dismiss());
  await author.page.locator('.workspaceCandidate [data-user="905"]').click();
  assert.equal((await outgoing())[0].helper_id,904);assert.equal(assignments,0);checks++;
  author.page.once('dialog',dialog=>dialog.accept());
  await author.page.locator('.workspaceCandidate [data-user="905"]').click();
  await author.page.waitForFunction(()=>hpointWorkspace.state.data.outgoing_offers.some(offer=>offer.helper_id===905));
  assert.equal(assignments,1);assert.deepEqual((await get(helper,'/api/helper/offers')).offers,[]);checks++;
  const stale=await author.context.request.post(base+'/api/helper/offers/withdraw',{data:{request_id:1,helper_id:904,offer_token:old.offer_token}});
  assert.equal(stale.status(),409);assert.equal((await outgoing())[0].helper_id,905);checks++;
  // Once accepted, cancellation of the pending invitation cannot undo the match.
  await other.page.goto(base+'/#/home');await other.page.locator('.workspaceOfferNotice').waitFor();
  const current=(await outgoing())[0];
  await other.page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await other.page.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
  const accepted=await author.context.request.post(base+'/api/helper/offers/withdraw',{data:{request_id:1,helper_id:905,offer_token:current.offer_token}});
  assert.equal(accepted.status(),409);
  assert.equal((await get(author,'/api/sync')).requests.find(row=>row.id===1).helper_id,905);
  assert.ok((await get(author,'/api/chats')).chats.some(chat=>chat.request_id===1));checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,invitations:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
