/* Mobile navigation, priority and discoverability on disposable data. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const {openHelpTab}=require('./help_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 let checks=0;
 try{
  await page.goto(base+'/auth/telegram?ticket=theme-browser-data');await page.locator('#hpointWorkspace').waitFor();
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,430,700,768,1440]){
    await page.setViewportSize({width,height:844});
    for(const route of ['#/home','#/help','#/profile','games']){
     await page.goto(base+'/'+route);
     await page.locator(route==='games'?'#games .game-card':'#hpointWorkspace').first().waitFor();
     const nav=page.locator(route==='games'?'.gamesPrimaryNav':'#sitePrimaryNav');
     assert.deepEqual(await nav.locator('button,a').allTextContents(),['Главная','Помощь','Игры','Активности']);
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width} ${route}`);
     if(width<=700){
      for(const button of await nav.locator('button,a').all()){
       const rect=await button.boundingBox();assert.ok(rect.height>=44&&rect.width>=44,'Touch targets');
       assert.ok(await button.evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=12),'Named navigation');
      }
      let rect=await nav.boundingBox();assert.ok(rect.y>=844-100&&rect.y+rect.height<=845,'Navigation at viewport bottom');
      await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
      rect=await nav.boundingBox();assert.ok(rect.y>=844-100&&rect.y+rect.height<=845,'Navigation stays reachable after scroll');
      await page.evaluate(()=>scrollTo(0,0));
      if(route==='#/home'){
       assert.equal(await page.locator('.homeMobileTitle').innerText(),'С чего начнём?');
       const focus=await page.locator('.homeTasks').boundingBox(),league=await page.locator('.homeLeague').boundingBox();
       assert.ok(focus.y<league.y,'Current help before community statistics');
       assert.equal(await page.locator('.peopleComposition').isVisible(),false);
       for(const action of ['request','help-tab'])assert.ok((await page.locator('.homeHero [data-ws-action="'+action+'"]').boundingBox()).height>=44);
      }
      if(route==='#/help'){
       assert.equal(await page.locator('.helpNavigation>button').count(),3);
       assert.equal(await page.locator('#helpMore').evaluate(e=>e.open),false);
       assert.equal(await page.locator('#wsRequestQuery').isVisible(),false);
      }
      if(route==='#/profile'){
       assert.equal(await page.locator('#accountMore').evaluate(e=>e.open),false);
       assert.equal(await page.locator('.workspaceProfileHero').isVisible(),true);
       await page.locator('#accountMore summary').click();
       await page.locator('.workspaceAccountNav [data-ws-action="account-menu"]').click();
       await page.locator('#modal .close').click();
      }
     }
     if(width===390)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,`simple-${colorScheme}-${route.replace(/[^a-z]/g,'')}.png`),fullPage:true,animations:'disabled'});
     checks++;
    }
   }
  }
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/#/help');
  await page.locator('#helpFilters summary').click();
  await page.locator('#wsRequestQuery').fill('Совместная');await page.locator('#wsRequestQuery').press('Enter');
  await page.waitForFunction(()=>hpointWorkspace.state.requestQuery==='Совместная');
  assert.equal(await page.locator('.workspaceRequest').count(),1);
  await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.locator('#wsRequestQuery').inputValue(),'Совместная');
  await page.locator('#wsRequestQuery').fill('');await page.locator('[data-ws-action="request-filter"]').click();
  await openHelpTab(page,'preferences');await page.locator('#wsHelperAvailability').fill('После 19:00');
  await page.setViewportSize({width:1440,height:900});
  await page.waitForFunction(()=>document.querySelectorAll('.helpNavigation>button').length===6);
  assert.equal(await page.locator('.helpNavigation>button').count(),6);
  assert.equal(await page.locator('#wsHelperAvailability').inputValue(),'После 19:00');
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>document.querySelectorAll('.helpNavigation>button').length===3);
  await openHelpTab(page,'mine');
  assert.equal(await page.locator('#helpMore').evaluate(e=>e.open),false);
  await page.locator('#sitePrimaryNav [data-route="home"]').click();await page.locator('.homeMobileTitle').waitFor();
  await page.locator('.workspaceHeaderActions [data-ws-action="request"]').click();
  await page.locator('#qw').waitFor();assert.equal(await page.locator('#modal').isVisible(),true);
  await page.locator('#modal .close').click();
  const guest=await browser.newContext({viewport:{width:320,height:740},isMobile:true,hasTouch:true});
  try{
   await guest.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
   const welcome=await guest.newPage();await welcome.goto(base+'/');
   await welcome.locator('#landing .hero .actions').waitFor();
   assert.equal(await welcome.locator('#sitePrimaryNav').count(),0);
   for(const button of await welcome.locator('#landing .hero .actions .btn').all()){
    const rect=await button.boundingBox();assert.ok(rect.height>=44&&rect.y+rect.height<740,'Login and registration on the first screen');
   }
   assert.equal(await welcome.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await welcome.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'simple-welcome.png'),fullPage:true,animations:'disabled'});
  }finally{await guest.close()}
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,searchAndDrafts:true,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
