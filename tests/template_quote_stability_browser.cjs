/* A stale quote response must never replace a newer value or another form. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext(),page=await context.newPage(),errors=[],held=new Map();let coalesced=0;
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.origin!==base)return route.abort();
  if(u.pathname==='/api/requests/quote'){
   const amount=u.searchParams.get('reward_rub');if(['401','402'].includes(amount)){held.set(amount,route);return}
   if(amount==='300')coalesced++;
  }return route.continue();
 });
 const set=amount=>page.evaluate(amount=>{rewardRub.value=amount;rewardRub.dispatchEvent(new Event('input',{bubbles:true}));hpointPersonal.ensureQuote().catch(()=>{});},String(amount));
 try{
  await emailLogin(page,'theme-browser-empty');await page.evaluate(()=>requestForm());await page.waitForFunction(()=>hpointPersonal.currentQuote()?.helper_rub===0);
  await set(401);await page.waitForTimeout(150);assert.ok(held.has('401'));
  await set(800);await page.waitForFunction(()=>hpointPersonal.currentQuote()?.helper_rub===800);
  await held.get('401').fulfill({status:500,contentType:'application/json',body:JSON.stringify({ok:false,error:'Synthetic old error'})});await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>hpointPersonal.currentQuote().total_rub),920);
  assert.match(await page.locator('#personalRequestQuote').innerText(),/920/);assert.doesNotMatch(await page.locator('#rqerr').innerText(),/error|проверить/);
  await set(402);await page.waitForTimeout(150);assert.ok(held.has('402'));await page.evaluate(()=>{closeModal();requestForm()});
  await page.waitForFunction(()=>hpointPersonal.currentQuote()?.helper_rub===0);
  await held.get('402').fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,quote:{helper_rub:402,commission_rub:60,total_rub:462,commission_percent:15,version:'top_up15_v1'}})});await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>hpointPersonal.currentQuote().helper_rub),0);assert.doesNotMatch(await page.locator('#personalRequestQuote').innerText(),/402|462/);
  await page.evaluate(async()=>{rewardRub.value='300';await Promise.all([hpointPersonal.ensureQuote(),hpointPersonal.ensureQuote(),hpointPersonal.ensureQuote()])});
  assert.equal(coalesced,1);assert.equal(await page.evaluate(()=>hpointPersonal.currentQuote().total_rub),345);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,staleErrorIgnored:true,oldFormResponseIgnored:true,duplicateReadsCoalesced:true,errors}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
