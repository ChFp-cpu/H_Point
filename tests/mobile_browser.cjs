/* Mobile help flows, using only the disposable run_theme_qa.py server. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844}});
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 let checks=0;
 try{
  await page.goto(base+'/auth/telegram?ticket=theme-browser-data');
  await page.locator('#hpointWorkspace').waitFor();
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,430,768,1440]){
    await page.setViewportSize({width,height:844});await page.goto(base+'/#/help');
    await page.locator('.helpNavigation').waitFor();
    await page.locator('.helpNavigation [data-tab="mine"]').click();
    assert.equal(await page.locator('#workspaceHistory').getAttribute('open'),null);
    await page.locator('#workspaceHistory summary').click();
    assert.equal(await page.locator('#workspaceHistory').evaluate(e=>e.open),true);
    await page.evaluate(()=>hpointWorkspace.refresh());
    assert.equal(await page.locator('#workspaceHistory').evaluate(e=>e.open),true,'Sync preserves the history fold');
    await page.locator('#workspaceHistory summary').click();
    for(const tab of ['mine','open','match','chats','preferences','map']){
     await page.locator('.helpNavigation [data-tab="'+tab+'"]').click();
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width} ${colorScheme} ${tab}`);
     if(width<500&&tab==='mine')assert.ok(await page.locator('#hpointWorkspace').evaluate(e=>e.getBoundingClientRect().height)<1000,'Requests screen is compact');
     checks++;
    }
    await page.goto(base+'/#/league');await page.locator('.leagueBoard').waitFor();
    await page.getByRole('button',{name:/Тестовый участник/}).first().click();
    await page.locator('.communityProfile').waitFor();
    assert.deepEqual(await page.locator('.communityProfile .progressMetric b').allTextContents(),['1','★ 5.0','0']);
    assert.ok(await page.locator('.communityProfile .progressMetrics').evaluate(e=>e.getBoundingClientRect().height)<150,'Reputation does not occupy a whole screen');
    await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`mobile-${colorScheme}-${width}-reputation.png`)});
    await page.locator('#modal .close').click();checks++;
   }
  }
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/#/help');
  await page.locator('.helpNavigation [data-tab="mine"]').click();
  let candidateRequests=0;page.on('request',r=>{if(r.url().endsWith('/api/assistant/candidates'))candidateRequests++});
  const matchButton=page.locator('.workspaceRequest').filter({has:page.getByRole('button',{name:'Подбор',exact:true})}).getByRole('button',{name:'Подбор',exact:true}).first();
  await matchButton.click();await page.locator('.workspaceCandidate').waitFor();
  assert.equal(candidateRequests,1);assert.equal(await page.locator('#wsMatchRequest').inputValue(),'1');
  const helper=await browser.newContext({viewport:{width:390,height:844}});
  await helper.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  const helperPage=await helper.newPage();helperPage.on('pageerror',e=>errors.push(e.message));
  await helperPage.goto(base+'/auth/telegram?ticket=mobile-helper');await helperPage.locator('#hpointWorkspace').waitFor();
  await helperPage.evaluate(()=>{window.geoAttempts=[];Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(ok,fail,options){geoAttempts.push(options);if(geoAttempts.length===1)fail({code:2});else ok({coords:{latitude:55.75,longitude:37.62}})}}})});
  await helperPage.locator('.workspaceHeaderActions [data-ws-action="request"]').click();
  assert.equal(await helperPage.evaluate(()=>geoAttempts.length),0,'Opening the form does not request GPS');
  await helperPage.locator('#qw').fill('Собственная заявка помощника');await helperPage.locator('#qc').selectOption('tech');
  await helperPage.locator('#requestNext').click();await helperPage.locator('#qp').fill('Тестовый город, дом 1');
  await helperPage.getByRole('button',{name:'◎ Определить моё местоположение',exact:true}).click();
  await helperPage.waitForFunction(()=>window.hpointRequestPoint?.lat===55.75);
  assert.deepEqual(await helperPage.evaluate(()=>geoAttempts.map(x=>x.enableHighAccuracy)),[false,true]);
  await helperPage.locator('#requestNext').click();
  await helperPage.locator('#createRequestButton').click();await helperPage.locator('#modal').waitFor({state:'hidden'});
  const own=await helper.request.get(base+'/api/sync').then(r=>r.json());
  const ownRequest=own.requests.find(r=>r.what==='Собственная заявка помощника');assert.ok(ownRequest);assert.equal(ownRequest.lat,55.75);
  await helperPage.locator('.helpNavigation [data-tab="preferences"]').click();
  await helperPage.locator('#wsHelperReady').check();await helperPage.locator('#wsHelperCategory_tech').check();
  await helperPage.locator('#wsHelperAvailability').fill('По будням после 18:00');
  await helperPage.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await helperPage.locator('#wsHelperCategory_tech').isChecked(),true);
  assert.equal(await helperPage.locator('#wsHelperAvailability').inputValue(),'По будням после 18:00');
  await helperPage.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await helperPage.waitForFunction(()=>hpointWorkspace.state.data.user.helper_availability==='По будням после 18:00');
  assert.equal((await helper.request.get(base+'/api/me').then(r=>r.json())).user.helper_ready,true);
  await page.locator('[data-ws-action="match-load"]').click();await page.locator('.workspaceCandidate').waitFor();
  await page.locator('[data-ws-action="assign"][data-user="904"]').click();
  await page.getByText('Ждём ответа помощников · 1',{exact:true}).waitFor();
  await helperPage.goto(base+'/#/home');await helperPage.getByRole('heading',{name:'Вас просят помочь',exact:true}).waitFor();
  await helperPage.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await helperPage.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
  await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal((await context.request.get(base+'/api/sync').then(r=>r.json())).requests.find(r=>r.id===1).status,'in_progress');
  await context.request.post(base+'/api/helper/preferences',{data:{categories:['tech'],availability:'Вечером',ready:true}});
  const reverse=await helper.request.post(base+'/api/assistant/candidates',{data:{request_id:ownRequest.id}}).then(r=>r.json());
  assert.ok(reverse.matches.some(r=>r.user_id===901));
  assert.ok((await helper.request.post(base+'/api/smart-match/assign',{data:{request_id:ownRequest.id,helper_id:901}})).ok());
  await page.goto(base+'/#/home');await page.getByRole('heading',{name:'Вас просят помочь',exact:true}).waitFor();
  await page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await page.locator('.workspaceOfferNotice').waitFor({state:'hidden'});
  assert.equal((await context.request.get(base+'/api/sync').then(r=>r.json())).requests.find(r=>r.id===ownRequest.id).status,'in_progress');
  await page.goto(base+'/games');await page.locator('#achievements .achievementGoals summary').click();
  assert.ok(await page.locator('#achievements .achievement.locked').count()>0);
  assert.equal((await context.request.get(base+'/api/games/state').then(r=>r.json())).achievements.length,0,'Looking at goals does not grant rewards');
  await helperPage.goto(base+'/#/help');await helperPage.locator('.helpNavigation').waitFor();
  await helperPage.evaluate(()=>helper());
  assert.match(await helperPage.locator('#toast').innerText(),/Сначала завершите текущую помощь/);
  assert.equal(await helperPage.locator('#modal').isVisible(),false,'An API rejection is not misreported as a GPS failure');
  await helperPage.evaluate(()=>{window.loadBigMap=async()=>{throw Error('test map failure')}});
  await helperPage.evaluate(()=>mapLocateMe());
  assert.match(await helperPage.locator('#toast').innerText(),/обновить карту/);
  await helperPage.evaluate(()=>{Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(ok,fail){fail({code:1})}}});requestForm()});
  await helperPage.evaluate(()=>requestDeviceLocation(false));
  assert.match(await helperPage.locator('#rqerr').innerText(),/запрещён/);
  assert.equal(await helperPage.evaluate(()=>window.hpointRequestPoint),null);
  checks+=3;
  checks+=10;await helper.close();
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,mobileFlows:true}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
