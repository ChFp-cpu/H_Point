/* The redesign remains a working product on small screens and live themes. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs'),{openHelpTab}=require('./help_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light',reducedMotion:'reduce'}),errors=[],external=[];let checks=0;
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();external.push(route.request().url());return route.abort()});
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 async function audit(label){
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,label+' horizontal overflow');checks++;
  const images=await page.locator('.hpPhotoImage').evaluateAll(nodes=>nodes.map(node=>({src:node.getAttribute('src'),alt:node.alt,w:node.getAttribute('width'),h:node.getAttribute('height'),loading:node.loading})));
  for(const img of images){assert.match(img.src,/^\/(?:assets\/|api\/photos\?)/);assert.ok(img.alt);assert.ok(Number(img.w)>0&&Number(img.h)>0);checks+=3}
  if(await page.locator('#hpointWorkspace').isVisible()){
   const support=page.locator('.workspaceHeaderActions [data-ws-action=support]');assert.equal(await support.isVisible(),true);checks++;
   if((await page.viewportSize()).width<=900){assert.equal(await page.locator('[data-header-mobile-wallet]').isVisible(),true);assert.match(await page.locator('[data-header-mobile-wallet]').innerText(),/HP.*₽/);checks+=2}
  }
 }
 async function shot(name){await page.evaluate(()=>{document.querySelectorAll('.hpPhotoImage').forEach(img=>img.loading='eager');scrollTo(0,0)});await page.waitForFunction(()=>[...document.querySelectorAll('.hpPhotoImage')].every(img=>img.complete&&img.naturalWidth>0));await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'editorial-'+name+'.png'),fullPage:true})}
 try{
  await page.goto(base);await page.locator('.hpWelcomeVisual').waitFor();assert.equal(await page.locator('.welcomeDirections [role=tab]').count(),2);checks++;
  for(const width of [320,375,768,1024,1440]){await page.setViewportSize({width,height:950});for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});await audit('welcome '+width+' '+colorScheme);
   const visual=page.locator('.hpWelcomeVisual'),mainPhoto=page.locator('.hpWelcomeMain .hpPhotoImage');
   assert.equal(await visual.isVisible(),true,'Welcome photograph must remain visible at '+width+' '+colorScheme);assert.equal(await mainPhoto.isVisible(),true);checks+=2;
   await mainPhoto.evaluate(image=>image.decode());assert.equal(await mainPhoto.evaluate(image=>image.naturalWidth>0&&image.naturalHeight>0),true);checks++;
   const cover=await page.locator('.cover.peopleCover').evaluate(node=>({height:node.getBoundingClientRect().height,before:getComputedStyle(node,':before').content,after:getComputedStyle(node,':after').content}));
   assert.equal(cover.before,'none');assert.equal(cover.after,'none');checks+=2;
   if(width<=375){const box=await visual.boundingBox(),actions=await page.locator('#landing .hero .actions').boundingBox();assert.ok(box.height>=260&&box.height<=340,'Compact mobile composition');assert.ok(cover.height<=box.height+50,'No legacy 420px minimum-height gap');assert.ok(actions.y+actions.height<=box.y,'Primary actions stay before the photograph');checks+=3;await shot('welcome-'+width+'-'+colorScheme)}
  }}
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointWorkspace.refresh());
  for(const width of [320,375,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:950});await page.emulateMedia({colorScheme});
   for(const route of ['home','help','profile','profile/wallet','profile/billing','activities','league']){await page.goto(base+'/#/'+route);await page.locator('#hpointWorkspace').waitFor();await page.evaluate(()=>hpointWorkspace.refresh());await audit(route+' '+width+' '+colorScheme)}
  }
  for(const [width,scheme] of [[1440,'light'],[375,'light'],[375,'dark']]){
   await page.setViewportSize({width,height:950});await page.emulateMedia({colorScheme:scheme});await page.goto(base+'/#/home');await page.locator('.hpHomeHero').waitFor();await shot('home-'+width+'-'+scheme);
   await page.goto(base+'/#/help');await page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(page,'open');await shot('help-'+width+'-'+scheme);
  }
  await page.locator('.isCompact [data-category=study]').click();assert.equal(await page.evaluate(()=>hpointWorkspace.state.requestCategory),'study');assert.equal(await page.locator('#wsRequestCategory').inputValue(),'study');checks+=2;
  await page.locator('.workspaceHeaderActions [data-ws-action=request]').click();await page.locator('#qw').fill('Новая заявка остаётся рабочей');await page.locator('#qc').selectOption('pets');await page.locator('#requestNext').click();assert.equal(await page.locator('#qp').isVisible(),true);checks++;await page.evaluate(()=>closeModal());
  await openHelpTab(page,'preferences');await page.locator('#wsHelperCategory_pets').check();await page.locator('.helperAdvanced summary').click();await page.locator('#wsHelperAvailability').fill('Тестовый черновик');const input=await page.locator('#wsHelperAvailability').elementHandle();await page.emulateMedia({colorScheme:'light'});await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await input.evaluate(node=>node===document.getElementById('wsHelperAvailability')),true);assert.equal(await page.locator('#wsHelperAvailability').inputValue(),'Тестовый черновик');checks+=2;
  await openHelpTab(page,'chats');assert.ok(await page.locator('.workspaceChatButton').count()>0);const activeChat=await page.evaluate(()=>hpointWorkspace.state.data.requests.find(row=>row.status==='in_progress').id);await page.locator('.workspaceChatButton[data-id="'+activeChat+'"]').click();await page.locator('#wsChatText').waitFor();await page.locator('#wsChatText').fill('Визуальная проверка чата');await page.locator('#wsChatText').press('Enter');await page.locator('.workspaceMessages').getByText('Визуальная проверка чата',{exact:false}).waitFor();checks+=2;await audit('chats');await openHelpTab(page,'match');await audit('matching');
  assert.deepEqual(external,[]);checks++;await openHelpTab(page,'map');await page.locator('#workspaceMapSlot').waitFor();await audit('map fallback');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,allRoutesResponsive:true,localPhotos:true,liveThemes:true,mobileWelcomePhotoVisible:true,realCategoryNavigation:true,draftsPreserved:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
