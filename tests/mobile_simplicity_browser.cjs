/* Current email-only navigation remains usable on touch screens. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,reducedMotion:'reduce'}),page=await context.newPage(),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());page.on('pageerror',e=>errors.push(e.message));
 try{
  await emailLogin(page,'theme-browser-data');
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:844});await page.emulateMedia({colorScheme});
   for(const route of ['home','help','profile','activities']){
    await page.goto(base+'/#/'+route);await page.locator('#hpointWorkspace').waitFor();const nav=page.locator('#sitePrimaryNav');assert.deepEqual(await nav.locator('button,a').evaluateAll(nodes=>nodes.map(node=>node.dataset.route)),['home','help','activities','admin']);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);checks+=2;
    assert.equal(await page.locator('.workspaceHeaderActions [data-ws-action=support]').isVisible(),true);checks++;
    if(width<=700){for(const button of await nav.locator('button,a').all()){const box=await button.boundingBox();assert.ok(box.width>=44&&box.height>=44);checks++}await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));const box=await nav.boundingBox();assert.ok(box.y>=744&&box.y+box.height<=845,'Navigation stays at the viewport bottom');checks++;await page.evaluate(()=>scrollTo(0,0))}
    if(route==='home'){const hero=page.locator('.hpHomeHero');for(const name of ['Нужна помощь','Хочу помочь']){const button=hero.getByRole('button',{name:new RegExp('^'+name)});assert.equal(await button.isVisible(),true);if(width<=700){const box=await button.boundingBox();assert.ok(box.height>=44&&box.y+box.height<774,'Primary home action fits first screen')}checks++}}
    if(route==='help'){assert.equal(await page.locator('.helpNavigation>button').count(),width<=700?3:5);assert.equal(await page.locator('.helpNavigation [data-tab=preferences]').count(),0);checks+=2}
    if(route==='profile'&&width<=700){assert.equal(await page.locator('#accountMore').evaluate(n=>n.open),false,JSON.stringify({width,colorScheme,state:await page.evaluate(()=>({open:hpointWorkspace.state.accountMoreOpen,mobile:matchMedia('(max-width:700px)').matches}))}));await page.locator('#accountMore summary').click();await page.locator('[data-ws-action=account-menu]').click();await page.locator('#modal').waitFor({state:'visible'});await page.evaluate(()=>closeModal());await page.locator('#accountMore summary').click();checks+=2}
   }
  }
  await page.setViewportSize({width:1440,height:844});await page.goto(base+'/#/profile');await page.locator('#accountMore').waitFor();assert.equal(await page.locator('#accountMore').evaluate(n=>n.open),true);await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.getElementById('accountMore')?.open===false);assert.equal(await page.locator('#accountMore').evaluate(n=>n.open),false);checks+=2;
  const games=await context.request.get(base+'/games');assert.equal(games.status(),410);assert.match(games.headers()['x-robots-tag'],/noindex/);checks+=2;
  await context.clearCookies();await page.goto(base);await page.locator('#landing .hero .actions').waitFor();await page.setViewportSize({width:320,height:740});await page.evaluate(()=>scrollTo(0,0));for(const button of await page.locator('#landing .hero .actions .btn').all()){const box=await button.boundingBox();assert.ok(box.height>=44&&box.y+box.height<740,JSON.stringify({label:await button.innerText(),box,viewport:await page.evaluate(()=>({w:innerWidth,h:innerHeight,scale:visualViewport.scale}))}));checks++}assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,currentEmailNavigation:true,touchTargets:true,homeChoices:true,moreSettings:true,gamesDisabled:true,errors}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
