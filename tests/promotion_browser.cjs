const {openHelpTab}=require('./help_navigation.cjs');
/* First-party request promotion: no real users, providers, or payments. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844}}),errors=[];
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));let checks=0,payments=0;
 page.on('request',request=>{if(request.url().includes('/api/payments/'))payments++});
 const get=async route=>context.request.get(base+route).then(response=>response.json());
 async function mine(){await page.goto(base+'/#/help');await page.locator('.helpNavigation [data-tab="mine"]').click();await page.locator('#hpointWorkspace').waitFor()}
 try{
  await page.goto(base+'/auth/telegram?ticket=theme-browser-data');await page.locator('#hpointWorkspace').waitFor();
  const before=await get('/api/sync'),historyBefore=(await get('/api/billing')).history.length;
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:844});await mine();
    const promo=page.locator('.workspaceRequestPromo');await promo.waitFor();
    assert.equal(await promo.count(),1);assert.match(await promo.innerText(),/49 ₽ или 25 HP/);
    assert.equal(await page.locator('.workspaceRequestList > .workspaceRequestPromo').count(),1,'The promotion is inline, not a popup or a fake request');
    assert.match(await promo.evaluate(element=>element.previousElementSibling.innerText),/#1 ·/,'The promotion follows its own open request, not a task already in progress');
    assert.ok((await promo.boundingBox()).height<=170,'Keep the promotion compact, including the second contextual offer');
    assert.match(await promo.innerText(),/PRO · 149 ₽ \/ 30 дней/);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks+=3;
    await page.locator('#workspaceHistory summary').click();assert.equal(await promo.count(),1,'No repeated ads among old requests');checks++;
    if(width===390||width===1440)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`promotion-${colorScheme}-${width}.png`),fullPage:true});
   }
  }
  for(const tab of ['open','match','chats','preferences']){
   await openHelpTab(page,tab);assert.equal(await page.locator('.workspaceRequestPromo').count(),0);checks++;
  }
  await mine();await page.getByRole('button',{name:'Скрыть предложение H-Point+',exact:true}).click();
  assert.equal(await page.locator('.workspaceRequestPromo').count(),0);
  await page.evaluate(()=>hpointWorkspace.refresh());await page.reload();await page.locator('.helpNavigation').waitFor();
  assert.equal(await page.locator('.workspaceRequestPromo').count(),0,'Dismissal survives sync and reload');checks++;
  await page.evaluate(()=>{localStorage.setItem('hpoint:request-promo:901',String(Date.now()-8*86400000))});
  await page.reload();await page.locator('.workspaceRequestPromo').waitFor();checks++;
  await page.locator('[data-ws-action="request-promo"][data-item="boost"]').click();await page.locator('.workspacePromoTarget').waitFor();
  assert.match(page.url(),/#\/profile\/billing$/);assert.match(await page.locator('.workspacePromoContext').innerText(),/Для заявки №1/);
  assert.match(await page.locator('.workspacePromoContext').innerText(),/не гарантирует отклик/);
  assert.equal(payments,0);assert.equal((await get('/api/me')).user.balance,before.user.balance);
  assert.equal((await get('/api/billing')).history.length,historyBefore);checks++;
  // A purchase requires a second, explicit choice, with the request prefilled.
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('.workspacePromoTarget [data-method="hp"]').click();assert.equal(payments,0);checks++;
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('.workspacePromoTarget [data-method="hp"]').click();
  await page.waitForFunction(()=>hpointWorkspace.state.data.requests.some(row=>row.id===1&&row.priority_boost===100));
  assert.equal(payments,1);assert.equal((await get('/api/me')).user.balance,before.user.balance-25);
  const history=(await get('/api/billing')).history;assert.equal(history.length,historyBefore+1);assert.equal(history[0].currency,'HP');
  assert.equal(JSON.parse(history[0].metadata).request_id,1);checks++;
  await mine();assert.equal(await page.locator('.workspaceRequestPromo').count(),0,'No upsell for an already promoted request');checks++;
  await page.goto(base+'/#/home');await page.locator('.homePaidOptions').waitFor();
  assert.equal(await page.locator('.homePaidOptions').count(),1);
  assert.match(await page.locator('.homePaidOptions').innerText(),/149 ₽ \/ 30 дней/);checks++;
  await page.getByRole('button',{name:'Скрыть предложение подписки',exact:true}).click();
  await page.reload();await page.locator('#hpointWorkspace').waitFor();
  assert.equal(await page.locator('.homePaidOptions').count(),0);checks++;
  await page.evaluate(()=>localStorage.removeItem('hpoint:home-promo:901'));
  await page.reload();await page.locator('.homePaidOptions').waitFor({state:'visible'});
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    // Read dimensions in one DOM operation: periodic sync may replace the card.
    const promoHeight=await page.locator('.homePaidOptions').evaluate(element=>element.getBoundingClientRect().height);
    assert.ok(promoHeight>0&&promoHeight<=200);
    if(width===390)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`paid-home-${colorScheme}-${width}.png`),fullPage:true});
    checks++;
   }
  }
  await page.locator('.homePaidOptions [data-item="pro"]').click();await page.locator('.workspacePromoTarget').waitFor();
  assert.equal(await page.locator('.workspaceProduct').count(),2);
  assert.match(await page.locator('.workspacePromoTarget').innerText(),/149 ₽ · 90 HP/);
  await page.locator('.workspacePromoTarget .workspaceProductDetails summary').click();
  assert.match(await page.locator('.workspacePromoTarget').innerText(),/\+8/);
  assert.match(await page.locator('.workspacePromoTarget').innerText(),/\+10/);
  assert.equal(payments,1,'Reading a subscription never makes a purchase');checks++;
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('.workspacePromoTarget [data-method="hp"]').click();
  await page.waitForFunction(()=>Boolean(hpointWorkspace.state.data.user.pro_until));
  assert.equal((await get('/api/me')).user.balance,before.user.balance-25-90);
  assert.equal((await get('/api/billing')).history.length,historyBefore+2);
  assert.equal((await get('/api/me')).user.stats.helped,before.user.stats.helped);
  await page.goto(base+'/#/home');
  assert.equal(await page.locator('.homePaidOptions').count(),0,'No upsell of an already active subscription');checks++;
  const historyCount=(await get('/api/billing')).history.length;
  for(const item of ['favorites','business','business_pro','ad','more_responses','verification']){
   const response=await context.request.post(base+'/api/payments/hp',{data:{item_type:item,purchase_key:'retired-'+item}});
   assert.equal(response.status(),409);checks++;
  }
  assert.equal((await get('/api/billing')).history.length,historyCount);
  await context.request.post(base+'/api/auth/logout',{data:{}});await page.reload();
  assert.equal(await page.locator('.workspaceRequestPromo').count(),0,'No advertising of closed features on registration');checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,promotion:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
