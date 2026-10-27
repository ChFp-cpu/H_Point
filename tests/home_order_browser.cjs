/* Authenticated homepage ordering, using only synthetic local email profiles. */
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
 const errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 try{
  await emailLogin(page,'theme-browser-data');
  await page.evaluate(()=>{localStorage.removeItem('hpoint:home-promo:901');window.closeModal?.();location.hash='#/home'});
  for(const colorScheme of ['light','dark'])for(const width of [390,1440]){
   await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:844});
   await page.evaluate(()=>hpointWorkspace.refresh());
   await page.locator('.homeCurrentColumn > .workspaceFocus').waitFor();
   await page.locator('.homePromoSlot > .homePaidOptions').waitFor();
   await page.locator('.homeTasks > .homeRecentCard').waitFor();
   await page.locator('.homeLeague').waitFor();
   const layout=await page.evaluate(()=>{
    const focus=document.querySelector('.homeCurrentColumn > .workspaceFocus'),ad=document.querySelector('.homePromoSlot > .homePaidOptions'),recent=document.querySelector('.homeTasks > .homeRecentCard'),league=document.querySelector('.homeLeague'),together=document.querySelector('.homeTogether');
    const box=node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}};
    const before=(a,b)=>Boolean(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING);
    return{focus:box(focus),ad:box(ad),recent:box(recent),league:box(league),order:[before(focus,ad),before(ad,recent),before(recent,league),before(league,together)],overflow:document.documentElement.scrollWidth>innerWidth};
   });
   assert.deepEqual(layout.order,[true,true,true,true]);checks++;
   assert.ok(layout.ad.y>=layout.focus.bottom-1,'The promotion follows the current step');
   assert.ok(Math.abs(layout.ad.x-layout.focus.x)<2,'The promotion shares the current-step column');
   assert.ok(Math.abs(layout.ad.width-layout.focus.width)<2);checks+=3;
   assert.ok(layout.league.y>=Math.max(layout.recent.bottom,layout.ad.bottom)-1,'League follows all task and promotion content');checks++;
   if(width<700){assert.ok(layout.recent.y>=layout.ad.bottom-1,'Mobile: current step, promotion, recent tasks, League');checks++}
   else{assert.ok(layout.recent.x>layout.focus.x+layout.focus.width-1,'Desktop recent tasks occupy the right column');checks++}
   assert.equal(layout.overflow,false);checks++;
   await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'home-order-'+colorScheme+'-'+width+'.png'),fullPage:true});
  }
  // Dismissing advertising removes only that slot; task/League order remains.
  await page.getByRole('button',{name:'Скрыть предложение подписки',exact:true}).click();
  await page.locator('.homePaidOptions').waitFor({state:'detached'});
  await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.locator('.homePaidOptions').count(),0);
  assert.match(await page.locator('.homePromoSlot').innerText(),/Работаете с клиентами/);
  assert.equal(await page.locator('.homeRecentCard').isVisible(),true);checks+=3;
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,checks,errors,homepageOrder:true,promotionUnderCurrentStep:true,recentTasksVisibleOnMobile:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
