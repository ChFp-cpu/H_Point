/* New lifecycle controls, synthetic local accounts only. */
const {openHelpTab}=require('./help_navigation.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();
  return {context,page};
 }
 const get=(actor,route)=>actor.context.request.get(base+route).then(r=>r.json());
 async function post(actor,route,data){let r=await actor.context.request.post(base+route,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function refresh(actor){await actor.page.evaluate(()=>hpointWorkspace.refresh())}
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  let wallet=(await get(author,'/api/wallet')).wallet;
  assert.equal(wallet.balance_rub,0);assert.equal(wallet.test_balance_rub,500);checks+=2;
  await author.page.goto(base+'/#/profile/wallet');await author.page.getByRole('heading',{name:'Тестовый баланс',exact:true}).waitFor();
  assert.match(await author.page.locator('#hpointWorkspace').innerText(),/500 ₽/);checks++;
  // Save structured helper preferences using the actual form.
  await helper.page.goto(base+'/#/help');await openHelpTab(helper.page,'preferences');
  await helper.page.locator('#wsHelperRadius').fill('10');
  await helper.page.locator('#wsHelperFrom').fill('2030-01-01T08:00');
  await helper.page.locator('#wsHelperUntil').fill('2030-01-01T18:00');
  await helper.page.locator('[data-ws-action="helper-preferences-save"]').click();
  await helper.page.waitForFunction(()=>hpointWorkspace.state.data.user.helper_radius_km===10);
  assert.equal((await get(helper,'/api/me')).user.helper_radius_km,10);checks++;
  await helper.page.locator('#wsHelperRadius').fill('0');await helper.page.locator('#wsHelperFrom').fill('');await helper.page.locator('#wsHelperUntil').fill('');
  await helper.page.locator('[data-ws-action="helper-preferences-save"]').click();
  await helper.page.waitForFunction(()=>hpointWorkspace.state.data.user.helper_radius_km===0);
  const job=await post(author,'/api/requests',{what:'Тестовые средства и обращение',place:'Тестовый район',time_needed:'по договорённости',urgency:'обычная',details:'Синтетические данные',category:'tech',reward_rub:400,scheduled_at:'2030-01-01T12:00:00+03:00'});
  const rid=job.request_id;
  assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===rid).scheduled_at,'2030-01-01T09:00:00+00:00');checks++;
  await post(author,'/api/requests/reward/reserve',{request_id:rid,amount_rub:400});
  await post(helper,'/api/requests/accept',{request_id:rid});
  await author.page.goto(base+'/#/help');await refresh(author);
  await author.page.locator('.helpNavigation [data-tab="mine"]').click();
  await author.page.locator('.workspaceRequest [data-ws-action="dispute"][data-id="'+rid+'"]').click();
  await author.page.locator('#disputeMessage').fill('Прошу уточнить результат помощи перед выплатой');
  await author.page.locator('#disputeSubmit').click();await author.page.locator('#modal').waitFor({state:'hidden'});
  await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(r=>r.id===id)?.dispute_status==='open',rid);
  assert.equal(await author.page.locator('[data-ws-action="finish"][data-id="'+rid+'"]').count(),0);checks++;
  const frozen=await author.context.request.post(base+'/api/requests/finish',{data:{request_id:rid}});
  assert.equal(frozen.status(),409);assert.equal((await get(helper,'/api/wallet')).wallet.test_balance_rub,0);checks+=2;
  const tickets=(await get(author,'/api/admin/dashboard')).tickets,ticket=tickets.find(t=>t.request_id===rid);
  assert.ok(ticket);checks++;
  await author.page.evaluate(()=>openAdminSupport());
  await author.page.locator('#adminReply'+ticket.id).fill('Результат согласован, разрешаю автору подтвердить помощь');
  author.page.once('dialog',d=>d.accept());
  await author.page.locator('.adminTicket').filter({has:author.page.locator('#adminReply'+ticket.id)}).getByRole('button',{name:'Разрешить завершение',exact:true}).click();
  await author.page.waitForFunction(async id=>(await fetch('/api/sync').then(r=>r.json())).requests.find(r=>r.id===id)?.dispute_status==='resolved',rid);
  assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===rid).dispute_status,'resolved');checks++;
  await author.page.evaluate(()=>closeModal());await refresh(author);
  await author.page.locator('[data-ws-action="paid-confirm"][data-id="'+rid+'"]').waitFor();
  author.page.once('dialog',d=>d.accept());await author.page.locator('[data-ws-action="paid-confirm"][data-id="'+rid+'"]').click();
  await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(r=>r.id===id)?.status==='done',rid);
  wallet=(await get(helper,'/api/wallet')).wallet;
  assert.equal(wallet.balance_rub,0);assert.equal(wallet.test_balance_rub,400);checks+=2;
  await helper.page.goto(base+'/#/profile/wallet');await refresh(helper);await helper.page.getByRole('heading',{name:'Тестовый баланс',exact:true}).waitFor();
  assert.match(await helper.page.locator('#hpointWorkspace').innerText(),/400 ₽/);checks++;
  for(const colorScheme of ['dark','light']){
   await helper.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){await helper.page.setViewportSize({width,height:844});assert.equal(await helper.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++}
   await helper.page.setViewportSize({width:390,height:844});await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'test-wallet-'+colorScheme+'.png'),fullPage:true});
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,testFundsStayTest:true,disputeWorkflow:true,helperPreferences:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
