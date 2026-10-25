const {openHelpTab}=require('./help_navigation.cjs');
/* Wallet-funded help: synthetic funds, no payment provider, two participants. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0,cardCalls=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(request.url().endsWith('/api/requests/reward/pay'))cardCalls++});
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();return {context,page};
 }
 const get=(actor,route)=>actor.context.request.get(base+route).then(response=>response.json());
 async function post(actor,route,data){let response=await actor.context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 const refresh=actor=>actor.page.evaluate(()=>hpointWorkspace.refresh());
 async function layout(actor,phase){
  for(const colorScheme of ['light','dark']){
   await actor.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await actor.page.setViewportSize({width,height:844});
    assert.equal(await actor.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,phase+' '+width+' '+colorScheme);checks++;
    if(width===390)await actor.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'paid-'+phase+'-'+colorScheme+'.png'),fullPage:true});
   }
  }
 }
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  const hpBefore=[(await get(author,'/api/me')).user.balance,(await get(helper,'/api/me')).user.balance];
  assert.equal((await get(author,'/api/wallet')).wallet.balance_rub,500);
  await author.page.locator('.workspaceHeaderActions [data-ws-action="request"]').click();
  await author.page.locator('#qw').fill('Платная помощь через кошелёк');await author.page.locator('#qc').selectOption('tech');
  await author.page.locator('#requestNext').click();await author.page.locator('#qp').fill('Тестовый район');
  await author.page.locator('#requestNext').click();await author.page.locator('.requestStep[data-request-step="2"] summary').click();
  await author.page.locator('#rewardRub').fill('400');await author.page.locator('#createRequestButton').click();
  await author.page.locator('#modal').waitFor({state:'hidden'});
  await author.page.locator('.workspaceCandidate [data-user="904"]').waitFor();
  const rid=(await get(author,'/api/sync')).requests.find(row=>row.what==='Платная помощь через кошелёк').id;
  assert.equal(await author.page.locator('#wsMatchRequest').inputValue(),String(rid),'A newly created request, not a previous one, is selected');
  assert.equal(await author.page.locator('.workspaceCandidate [data-user="904"]').getAttribute('data-id'),String(rid));checks++;
  assert.equal(cardCalls,0,'Creating a paid request must not initiate payment');checks++;
  await author.page.locator('.workspaceCandidate [data-user="904"]').click();
  await author.page.waitForFunction(()=>hpointWorkspace.state.data.outgoing_offers.length>0);
  await author.page.locator('.rewardReservePanel [data-ws-action="reward-reserve"]').waitFor();
  assert.equal((await get(author,'/api/sync')).outgoing_offers[0].helper_id,904);
  assert.equal((await get(author,'/api/wallet')).wallet.balance_rub,500);checks++;
  await helper.page.goto(base+'/#/home');await helper.page.locator('.workspaceOfferNotice').waitFor();
  assert.equal(await helper.page.locator('.workspaceOfferNotice [data-accept="true"]').isDisabled(),true);
  assert.match(await helper.page.locator('.workspaceOfferNotice').innerText(),/400 ₽/);checks++;
  await layout(author,'unfunded');
  author.page.once('dialog',dialog=>dialog.dismiss());await author.page.locator('[data-ws-action="reward-reserve"]').click();
  assert.equal((await get(author,'/api/wallet')).wallet.balance_rub,500,'Cancelling confirmation never reserves funds');checks++;
  author.page.once('dialog',dialog=>dialog.accept());await author.page.locator('[data-ws-action="reward-reserve"]').click();
  await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(row=>row.id===id)?.reward_payment_status==='paid',rid);
  const reserve=(await get(author,'/api/wallet')).wallet;
  assert.equal(reserve.balance_rub,100);assert.equal(reserve.reserved_rub,400);
  assert.equal((await get(helper,'/api/wallet')).wallet.balance_rub,0);checks++;
  await refresh(helper);await helper.page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await helper.page.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
  await helper.page.goto(base+'/#/help');await helper.page.locator('.helpNavigation [data-tab="mine"]').click();
  await helper.page.locator('[data-ws-action="finish"][data-id="'+rid+'"]').click();
  await helper.page.waitForFunction(id=>Boolean(hpointWorkspace.state.data.requests.find(row=>row.id===id)?.completion_requested_at),rid);
  assert.equal((await get(helper,'/api/wallet')).wallet.balance_rub,0,'Reporting completion is not payout');checks++;
  await refresh(author);await author.page.locator('.paidConfirmation').waitFor();await layout(author,'confirmation');
  author.page.once('dialog',dialog=>dialog.dismiss());await author.page.locator('[data-ws-action="paid-confirm"]').click();
  assert.equal((await get(helper,'/api/wallet')).wallet.balance_rub,0);checks++;
  author.page.once('dialog',dialog=>dialog.accept());await author.page.locator('[data-ws-action="paid-confirm"]').click();
  await author.page.locator('.paidConfirmation').waitFor({state:'hidden'});
  assert.equal((await get(helper,'/api/wallet')).wallet.balance_rub,400);
  assert.equal((await get(author,'/api/wallet')).wallet.reserved_rub,0);
  assert.deepEqual([(await get(author,'/api/me')).user.balance,(await get(helper,'/api/me')).user.balance],hpBefore);checks++;
  const duplicate=await author.context.request.post(base+'/api/requests/completion/confirm',{data:{request_id:rid}});
  assert.equal(duplicate.status(),409);assert.equal((await get(helper,'/api/wallet')).wallet.balance_rub,400);checks++;
  // A zero-wallet author can still invite; the UI explains the funding block.
  const empty=await login('theme-browser-empty');
  await post(helper,'/api/helper/queue',{});
  const another=await post(empty,'/api/requests',{what:'Без средств на кошельке',place:'Тест',time_needed:'сегодня',urgency:'обычная',details:'test',category:'tech',reward_rub:400});
  await refresh(empty);
  await empty.page.goto(base+'/#/help');await openHelpTab(empty.page,'match');
  await empty.page.locator('.workspaceCandidate [data-user="904"]').click();
  await empty.page.locator('.rewardReservePanel [data-ws-action="reward-reserve"]').waitFor();
  assert.equal(await empty.page.locator('[data-ws-action="reward-reserve"]').isDisabled(),true);
  assert.match(await empty.page.locator('.rewardReservePanel').innerText(),/Для резерва не хватает 400 ₽/);
  assert.equal(await empty.page.locator('[data-ws-action="reward-card"]').count(),0,'No broken card button when the merchant is not configured');
  const denied=await empty.context.request.post(base+'/api/requests/reward/reserve',{data:{request_id:another.request_id,amount_rub:400}});
  assert.equal(denied.status(),409);assert.equal((await get(empty,'/api/sync')).outgoing_offers.length,1);checks++;
  await layout(empty,'empty-wallet');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,paidWalletFlow:true,realPayments:false}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
