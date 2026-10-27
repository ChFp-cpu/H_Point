const {emailLogin}=require('./email_browser_login.cjs');
const {openHelpTab}=require('./help_navigation.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());await context.addInitScript(()=>{window.qaGeoCalls=0;Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(){window.qaGeoCalls++;throw Error('Automatic GPS must not be requested')}}})});const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await emailLogin(page,ticket);return{context,page}}
 async function get(actor,url){const r=await actor.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(actor,url,data){const r=await actor.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function refresh(actor){await actor.page.evaluate(()=>hpointWorkspace.refresh())}
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  for(const endpoint of ['/api/auth/telegram/start','/api/payments/create','/api/requests/reward/pay']){const r=await author.context.request.post(base+endpoint,{data:{}});assert.ok([409,410].includes(r.status()));checks++}
  // An explicit mode replaces location permission prompts.
  await helper.page.goto(base+'/#/help');await helper.page.evaluate(()=>helper());await helper.page.locator('#hpHelperLocation').fill('Тестовый район');await helper.page.locator('#hpEnterHelper').click();
  await helper.page.waitForFunction(()=>hpointWorkspace.state.data.user.helper_ready===true);
  await helper.page.getByRole('button',{name:'Настроить помощь',exact:true}).waitFor();assert.equal((await get(helper,'/api/me')).user.helper_ready,true);checks++;
  // The reserve is offered immediately, before matching anyone.
  await author.page.locator('.workspaceHeaderActions [data-ws-action="request"]').click();
  await author.page.locator('#qw').fill('Настройка ноутбука с резервом');await author.page.locator('#qc').selectOption('tech');await author.page.locator('#requestNext').click();
  await author.page.locator('#qp').fill('Тестовый адрес');await author.page.locator('#requestNext').click();
  await author.page.locator('.requestStep[data-request-step="2"] summary').click();await author.page.locator('#rewardRub').fill('400');await author.page.locator('#createRequestButton').click();
  await author.page.locator('#hpCreateReserve').waitFor();assert.match(await author.page.locator('#modalbody').innerText(),/340 тест/);checks++;
  const job=(await get(author,'/api/sync')).requests.find(r=>r.what==='Настройка ноутбука с резервом'),rid=job.id;
  assert.ok(Date.parse(job.reserve_deadline_at)-Date.now()<=300000);assert.ok(Date.parse(job.reserve_deadline_at)>Date.now());checks+=2;
  await author.page.locator('#hpCreateReserve').click();await author.page.locator('#modal').waitFor({state:'hidden'});
  assert.equal((await get(author,'/api/wallet')).wallet.balance_rub,100);checks++;
  await author.page.evaluate(id=>openRequestTracking(id),rid);await author.page.getByRole('heading',{name:'Настройка ноутбука с резервом',exact:true}).waitFor();await author.page.evaluate(()=>closeModal());checks++;
  await helper.page.goto(base+'/#/help');await refresh(helper);await openHelpTab(helper.page,'open');
  const card=helper.page.locator('.workspaceRequest').filter({hasText:'Настройка ноутбука с резервом'});assert.doesNotMatch(await card.innerText(),/#\d|№\s*\d/);assert.match(await card.innerText(),/Тестовый участник/);checks+=2;
  await card.getByRole('button',{name:'Хочу помочь',exact:true}).click();await helper.page.locator('#hpEnterHelper').click();await helper.page.locator('#wsChatText').waitFor();assert.match(await helper.page.locator('.workspaceChatPanel h3').innerText(),/Настройка ноутбука/);checks++;
  await refresh(author);await author.page.evaluate(id=>hpointWorkspace.openChat(id),rid);
  author.page.once('dialog',d=>d.accept());await author.page.locator('[data-ws-action="chat-select"]').click();
  await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(r=>r.id===id)?.status==='in_progress',rid);checks++;
  author.page.once('dialog',d=>d.accept());await author.page.locator('[data-ws-action="finish"][data-id="'+rid+'"]').click();
  await author.page.getByRole('heading',{name:'Как прошло взаимодействие?',exact:true}).waitFor();await author.page.locator('#hpSendReview').click();await author.page.locator('#modal').waitFor({state:'hidden'});checks++;
  await refresh(helper);await helper.page.getByRole('heading',{name:'Как прошло взаимодействие?',exact:true}).waitFor();await helper.page.locator('[name="hpReviewRating"][value="4"]').check();await helper.page.locator('#hpSendReview').click();await helper.page.locator('#modal').waitFor({state:'hidden'});checks++;
  assert.equal((await get(helper,'/api/wallet')).wallet.test_balance_rub,340);assert.equal((await get(author,'/api/admin/dashboard')).platform_income.earned_test_rub,60);checks+=2;
  const another=await post(author,'/api/requests',{what:'Отменяемая помощь',place:'Тест',time_needed:'сегодня',urgency:'обычная',details:'Тест'});
  await refresh(author);await openHelpTab(author.page,'mine');author.page.on('dialog',d=>d.accept(d.type()==='prompt'?'Планы изменились':undefined));
  await author.page.locator('.workspaceRequest').filter({hasText:'Отменяемая помощь'}).getByRole('button',{name:'Отменить',exact:true}).click();
  await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(r=>r.id===id)?.status==='cancelled',another.request_id);checks++;
  await author.page.goto(base+'/#/profile/wallet');await refresh(author);assert.equal(await author.page.getByRole('heading',{name:'Реальные средства',exact:true}).count(),0);checks++;
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){await author.page.emulateMedia({colorScheme});await author.page.setViewportSize({width,height:844});assert.equal(await author.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);if(width<700){const bounds=await author.page.locator('#sitePrimaryNav').boundingBox();assert.ok(Math.abs(bounds.x+bounds.width/2-width/2)<2);assert.ok(bounds.width<=width-20);await author.page.waitForFunction(()=>[...document.querySelectorAll('#sitePrimaryNav button')].every(e=>e.isConnected&&getComputedStyle(e).justifyContent==='center'));const alignment=await author.page.evaluate(()=>[...document.querySelectorAll('#sitePrimaryNav button')].map(e=>getComputedStyle(e).justifyContent));assert.ok(alignment.length>0);assert.ok(alignment.every(value=>value==='center'))}checks++;if(width===390)await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'new-workflow-'+colorScheme+'.png'),fullPage:true})}
  for(const actor of [author,helper])assert.equal(await actor.page.evaluate(()=>window.qaGeoCalls),0);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,emailOnly:true,testMoneyOnly:true,commission15:true,reserveImmediately:true,ratingsBothSides:true,helperMode:true,noAutomaticGps:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
