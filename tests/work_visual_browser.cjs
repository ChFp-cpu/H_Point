/* Work photography remains honest and the existing forms still own the workflow. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs'),{workTab}=require('./work_browser_navigation.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),page=await context.newPage(),errors=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());page.on('pageerror',error=>errors.push(error.message));
 const post=async(url,data)=>{const response=await context.request.post(base+url,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 try{
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointCommercial.openCreation());
  const form=page.locator('[data-commercial-form="profile"]');await form.waitFor();
  assert.equal(await form.locator('[data-commercial-action="choose-kind"]').count(),9);assert.equal(await form.locator('[name=kind] option:not([value=""])').count(),9);checks+=2;
  await form.locator('[data-kind=trainer]').click();assert.equal(await form.locator('[name=kind]').inputValue(),'trainer');assert.equal(await form.locator('[data-kind=trainer]').getAttribute('aria-pressed'),'true');checks+=2;
  await form.locator('[name=kind]').selectOption('foreman');assert.equal(await form.locator('[data-kind=foreman]').getAttribute('aria-pressed'),'true');assert.equal(await form.locator('[data-kind=trainer]').getAttribute('aria-pressed'),'false');checks+=2;
  await form.locator('[name=title]').fill('Проверка живого рабочего кабинета');await form.locator('[name=description]').fill('Только синтетическая локальная организация.');
  await form.evaluate(node=>window.qaVisualWorkForm=node);await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await form.evaluate(node=>node===window.qaVisualWorkForm),true);assert.equal(await form.locator('[name=kind]').inputValue(),'foreman');checks+=2;
  for(const width of [320,375,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:950});await page.emulateMedia({colorScheme});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Creation overflow '+width);checks++;
  }
  await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({colorScheme:'light'});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'work-creation-visual-desktop.png'),fullPage:true});
  await form.locator('[name=kind]').selectOption('trainer');await form.locator('button[type=submit]').click();await page.waitForURL('**/#/work');await page.locator('.professionalWelcome').waitFor();
  assert.match(await page.locator('.professionalWelcome h2').textContent(),/людей/);assert.equal(await page.locator('.commercialFocusMetrics').count(),0);assert.match(await page.locator('.professionalNextWork').textContent(),/первую запись/);checks+=3;
  assert.equal(await page.locator('.professionalWelcome .professionalPhotoLabel').textContent(),'Фото направления');checks++;
  const photo=page.locator('.professionalWelcome img');assert.equal(await photo.count(),1);assert.match(await photo.getAttribute('src'),/^\/assets\/.*\.webp$/);assert.ok(await photo.getAttribute('width'));assert.ok(await photo.getAttribute('height'));checks+=4;
  for(const width of [320,375,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:950});await page.emulateMedia({colorScheme});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Work overview overflow '+width);checks++;
   if([320,375,1440].includes(width)){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'work-overview-'+width+'-'+colorScheme+'.png'),fullPage:true})};
  }
  // A picture is not a fake case: only actual saved records enter this overview.
  await post('/api/commercial/clients',{name:'Синтетический клиент',active:true});const data=await(await context.request.get(base+'/api/commercial')).json(),client=data.commercial.clients[0];
  await post('/api/commercial/bookings',{client_id:client.id,title:'Тестовая тренировка в расписании',starts_at:'2030-05-01T10:00:00+00:00',duration_minutes:60,price_rub:0,status:'planned'});await page.evaluate(()=>hpointCommercial.refresh());assert.match(await page.locator('.professionalNextWork').textContent(),/Тестовая тренировка/);checks++;
  await page.locator('.professionalQuickLinks [data-tab=bookings]').click();await page.locator('[data-commercial-form=bookings]').waitFor();assert.equal(await page.locator('.professionalWelcome').count(),0);checks++;
  await workTab(page,'overview');await page.locator('.professionalWelcome').waitFor();await workTab(page,'professional:athletes');await page.locator('[data-commercial-form="professional/athletes"]').waitFor();assert.equal(await page.locator('.professionalWelcome').count(),0);checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,photoChooser:true,realDataOnly:true,existingToolsPreserved:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
