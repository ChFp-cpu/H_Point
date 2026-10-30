/* Disposable local accounts and test funds only. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:950}}),errors=[];
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));let checks=0;
 const get=async route=>context.request.get(base+route).then(response=>response.json());
 const proCard=()=>page.locator('.workspaceProduct').filter({has:page.locator('[data-item="pro"]')});
 const billing=async()=>{await page.goto(base+'/#/profile/billing');await page.locator('[data-pro-status]').waitFor();};
 const post=async(route,data)=>{let response=await context.request.post(base+route,{data});return {status:response.status(),data:await response.json()}};
 try{
  await emailLogin(page,'theme-browser-data');
  const before=await get('/api/billing'),walletBefore=(await get('/api/sync')).wallet.test_balance_rub;
  assert.equal(before.subscription.pro.active,false);assert.ok(walletBefore>=298,'Run with HPOINT_QA_TEST_FUNDS=1');checks+=2;
  await billing();assert.equal(await page.locator('[data-pro-status="inactive"]').count(),1);
  assert.equal(await page.locator('[data-header-pro]:not([hidden])').count(),0);checks+=2;
  // Follow the real home advert: its remembered promotion context must not
  // replace the post-purchase renewal controls with another purchase offer.
  await page.goto(base+'/#/home');await page.locator('.homePaidOptions [data-item="pro"]').click();
  await page.locator('.workspacePromoTarget').waitFor();
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.promotionItem),'pro');
  assert.match(await proCard().locator('[data-method="wallet"]').innerText(),/Оплатить/);checks+=2;
  page.once('dialog',dialog=>dialog.accept());await proCard().locator('[data-method="wallet"]').click();
  await page.waitForFunction(()=>hpointWorkspace.state.data.user.pro_active===true);
  await page.locator('[data-pro-status="active"]').waitFor();
  const bought=await get('/api/billing'),until=bought.subscription.pro.ends_at;
  assert.equal(bought.subscription.pro.days_remaining,30);
  assert.equal(bought.history.length,before.history.length+1);
  assert.equal(bought.subscription.history[0].invoice_id,bought.history[0].id);checks+=3;
  assert.match(await page.locator('[data-pro-status="active"]').innerText(),/PRO активен/);
  assert.match(await page.locator('[data-pro-status="active"]').innerText(),/Осталось 30 дней/);
  assert.match(await proCard().innerText(),/Подключён до/);
  assert.match(await proCard().locator('[data-method="wallet"]').innerText(),/Продлить/);
  assert.doesNotMatch(await proCard().locator('.workspaceProductActions').innerText(),/Оплатить/);
  assert.equal(await page.locator('.workspacePromoTarget').count(),0);
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.promotionItem),null);checks+=3;
  await page.locator('[data-header-pro]').waitFor({state:'visible'});checks+=5;
  await page.goto(base+'/#/profile');await page.locator('.workspaceProfileHero .workspaceProBadge').waitFor();
  assert.equal(await page.locator('.workspaceProfileHero .workspaceProBadge').innerText(),'PRO');checks++;
  await billing();
  const silent=await post('/api/payments/wallet',{item_type:'pro',metadata:{},purchase_key:'browser-silent-term'});
  assert.equal(silent.status,409);assert.match(silent.data.error,/уже активен/);
  assert.equal((await get('/api/billing')).history.length,bought.history.length);checks+=3;
  page.once('dialog',dialog=>dialog.dismiss());await proCard().locator('[data-method="wallet"]').click();
  assert.equal((await get('/api/billing')).history.length,bought.history.length);
  assert.equal((await get('/api/billing')).subscription.pro.ends_at,until);checks+=2;
  let renewalBody;
  page.on('request',request=>{if(request.url().endsWith('/api/payments/wallet'))renewalBody=request.postDataJSON()});
  page.once('dialog',async dialog=>{assert.match(dialog.message(),/Продлить действующий PRO на 30 дней/);await dialog.accept()});
  await proCard().locator('[data-method="wallet"]').click();
  await page.waitForFunction(previous=>hpointWorkspace.state.data.user.pro_until!==previous,until);
  const renewed=await get('/api/billing');
  assert.equal(new Date(renewed.subscription.pro.ends_at)-new Date(until),30*86400000);
  assert.equal(renewed.subscription.pro.days_remaining,60);
  assert.equal(renewed.history.length,bought.history.length+1);
  assert.equal(renewalBody.metadata.renew,true);assert.equal(renewalBody.metadata.expected_until,until);checks+=5;
  const replay=await post('/api/payments/wallet',renewalBody);
  assert.equal(replay.status,200);assert.equal(replay.data.created,false);
  const stale=await post('/api/payments/wallet',{...renewalBody,purchase_key:'browser-stale-tab-term'});
  assert.equal(stale.status,409);assert.match(stale.data.error,/Срок подписки изменился/);
  assert.equal((await get('/api/billing')).history.length,renewed.history.length);checks+=5;
  await page.reload();await page.locator('[data-pro-status="active"]').waitFor();
  assert.match(await page.locator('[data-pro-status="active"]').innerText(),/Осталось 60 дней/);
  assert.match(await proCard().innerText(),/Продлить/);checks+=2;
  // An open page must stop offering a renewal from a stale active snapshot
  // once its recorded deadline has passed, even before the next billing fetch.
  const expiredSnapshot=await page.evaluate(snapshot=>{
   const subscription={...snapshot.subscription,pro:{...snapshot.subscription.pro,active:true,ends_at:'2020-01-01T00:00:00+00:00'}};
   const host=document.createElement('div');host.innerHTML=hpointSubscriptions.renderBilling({...snapshot,subscription});
   return {status:host.querySelector('[data-pro-status]').dataset.proStatus,renewals:host.querySelectorAll('[data-renew]').length,metadata:hpointSubscriptions.purchaseMetadata('pro',subscription)};
  },renewed);
  assert.equal(expiredSnapshot.status,'expired');assert.equal(expiredSnapshot.renewals,0);assert.deepEqual(expiredSnapshot.metadata,{});checks+=3;
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:950});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('[data-pro-status="active"]').count(),1);checks+=2;
    if(width===390)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`subscriptions-${colorScheme}-${width}.png`),fullPage:true});
   }
  }
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({ok:true,checks,errors,subscriptions:true}));
 }catch(error){console.error('Subscription UI:',await page.locator('#hpointWorkspace').innerText().catch(()=>''));console.error('Errors:',errors);await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'subscriptions-failure.png'),fullPage:true}).catch(()=>{});throw error}
 finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
