/* Current PRO offers and retired sales, using disposable local email accounts. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs'),{openHelpTab}=require('./help_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),errors=[];let checks=0,paymentRequests=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(request.url().includes('/api/payments/'))paymentRequests++});
 const get=async route=>(await context.request.get(base+route)).json();
 const retired=['boost','more_responses','verification','favorites','business','business_pro','ad'];
 async function noSales(label){for(const item of retired){assert.equal(await page.locator('[data-ws-action="buy"][data-item="'+item+'"], [data-ws-action="request-promo"][data-item="'+item+'"]').count(),0,label+' retired purchase '+item);checks++}assert.equal(await page.locator('.workspaceRequestList > .workspaceRequestPromo').count(),0,label+' no paid request boost advert');checks++}
 async function audit(label){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,label+' horizontal overflow');checks++;await noSales(label)}
 async function home(){await page.goto(base+'/#/home');await page.locator('.hpHomeHero').waitFor()}
 async function mine(){await page.goto(base+'/#/help');await page.locator('.helpNavigation').waitFor();await openHelpTab(page,'mine')}
 try{
  await emailLogin(page,'theme-browser-data');
  const before=await get('/api/sync'),billingBefore=await get('/api/billing');
  assert.deepEqual(Object.keys(billingBefore.catalog),['pro']);assert.equal(billingBefore.catalog.pro.rub,149);assert.equal(billingBefore.catalog.pro.hp,90);checks+=3;
  for(const scheme of ['light','dark'])for(const width of [320,375,768,1440]){
   await page.emulateMedia({colorScheme:scheme});await page.setViewportSize({width,height:844});await mine();
   assert.equal(await page.locator('.workspaceRequestPromo').count(),0,'No per-request promotion offered');checks++;await audit('Help own '+width+' '+scheme);
   for(const tab of ['open','match','chats','preferences']){if(tab==='preferences')await openHelpTab(page,'open');await openHelpTab(page,tab);await audit('Help '+tab+' '+width+' '+scheme)}
   await home();const advert=page.locator('.homePaidOptions');await advert.waitFor();assert.equal(await advert.count(),1);assert.match(await advert.innerText(),/PRO/);assert.match(await advert.innerText(),/5 активных заявок/);assert.match(await advert.innerText(),/шаблоны|повторы/i);assert.ok((await advert.boundingBox()).height<=260,'The existing home offer stays compact');checks+=5;await audit('Home '+width+' '+scheme);
   if(width===375)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'personal-offers-'+scheme+'-'+width+'.png'),fullPage:true});
  }
  await page.getByRole('button',{name:'Скрыть предложение подписки',exact:true}).click();assert.equal(await page.locator('.homePaidOptions').count(),0);checks++;
  await page.evaluate(()=>hpointWorkspace.refresh());await page.reload();await page.locator('.hpHomeHero').waitFor();assert.equal(await page.locator('.homePaidOptions').count(),0,'Dismissal survives sync/reload');checks++;
  await page.evaluate(uid=>localStorage.setItem('hpoint:home-promo:'+uid,String(Date.now()-8*86400000)),before.current_user_id);
  await page.reload();await page.locator('.homePaidOptions').waitFor();checks++;
  const navigatePayments=paymentRequests;
  await page.locator('.homePaidOptions [data-item="pro"]').click();await page.locator('.subscriptionPlanGrid').waitFor();
  assert.match(page.url(),/#\/profile\/billing$/);assert.equal(await page.locator('.subscriptionPlanGrid > .workspaceProduct').count(),3);assert.deepEqual(await page.locator('.subscriptionPlanGrid > .workspaceProduct h3').allTextContents(),['Бесплатно','H-Point PRO','Для работы']);checks+=3;
  const plans=page.locator('.subscriptionPlanGrid');assert.match(await plans.innerText(),/1 собственная активная заявка/);assert.match(await plans.innerText(),/2 публикации активностей/);assert.match(await plans.innerText(),/5 собственных активных заявок/);assert.match(await plans.innerText(),/149 тест\. ₽ или 90 HP/);assert.match(await plans.innerText(),/490 тест\. ₽/);assert.match(await plans.innerText(),/7 дней бесплатно/);checks+=6;
  assert.equal(paymentRequests,navigatePayments,'Reading PRO conditions never purchases anything');assert.equal((await get('/api/billing')).history.length,billingBefore.history.length);assert.equal((await get('/api/me')).user.balance,before.user.balance);assert.equal((await get('/api/sync')).wallet.test_balance_rub,before.wallet.test_balance_rub);checks+=4;
  for(const scheme of ['light','dark'])for(const width of [320,375,768,1440]){await page.emulateMedia({colorScheme:scheme});await page.setViewportSize({width,height:844});await audit('Billing '+width+' '+scheme)}
  for(const endpoint of ['/api/payments/hp','/api/payments/wallet'])for(const item of retired){
   const response=await context.request.post(base+endpoint,{data:{item_type:item,request_id:before.requests[0].id,metadata:{request_id:before.requests[0].id},purchase_key:'retired-browser-'+endpoint.split('/').pop()+'-'+item}});
   assert.equal(response.status(),409,endpoint+' '+item+' must reject stale sale requests');checks++;
  }
  const after=await get('/api/sync'),afterBilling=await get('/api/billing');
  assert.equal(after.user.balance,before.user.balance);assert.equal(after.wallet.test_balance_rub,before.wallet.test_balance_rub);assert.equal(afterBilling.history.length,billingBefore.history.length);assert.deepEqual(after.requests.map(r=>[r.id,r.priority_boost]),before.requests.map(r=>[r.id,r.priority_boost]));checks+=4;
  await context.request.post(base+'/api/auth/logout',{data:{}});await page.reload();await page.locator('.nav.guestHeader').waitFor();assert.equal(await page.locator('.homePaidOptions,.workspaceRequestPromo').count(),0);assert.equal(await page.locator('.welcomeDirections [role=tab]').count(),2);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,emailOnly:true,proOnlyCatalog:true,threePlanComparison:true,retiredSalesRejected:true,noRetiredDebits:true,noBoostAdverts:true,homeOfferDismissal:true}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
