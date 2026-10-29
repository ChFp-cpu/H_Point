'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket){const context=await browser.newContext();contexts.push(context);await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));await emailLogin(page,ticket);return {context,page}}
 async function post(actor,url,data){const response=await actor.context.request.post(base+url,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 try{
  const owner=await actor('theme-browser-data'),empty=await actor('mobile-helper');
  const title='Тестовый центр индивидуальных тренировок и подготовки к соревнованиям';
  await post(owner,'/api/commercial/profile',{kind:'trainer',title,description:'PRIVATE BUSINESS DESCRIPTION',contact:''});
  const service=(await post(owner,'/api/commercial/services',{title:'Подготовка к любительским соревнованиям и разбор техники упражнений',description:'Реальное тестовое предложение. <script>window.publicXss=1</script>',price_rub:1200,duration_minutes:45})).result.id;
  await post(owner,'/api/commercial/clients',{name:'PRIVATE CLIENT',contact:'private@example.test',notes:'PRIVATE HEALTH NOTE'});
  await post(owner,'/api/commercial/public-profile',{slug:'public-photo-trainer',published:true,description:'Индивидуальная работа по опубликованным условиям. Уточните детали у организации.',contact:'Публичный контакт: +7 (000) 000-00-00',address:'Публичный тестовый район'});
  await post(owner,'/api/commercial/services/publish',{id:service,published:true});
  await post(empty,'/api/commercial/profile',{kind:'foreman',title:'Тестовая строительная команда',description:'PRIVATE DESCRIPTION',contact:''});
  await post(empty,'/api/commercial/public-profile',{slug:'public-photo-empty',published:true,description:'',contact:'',address:''});
  const context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light',reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  const response=await page.goto(base+'/organizations/public-photo-trainer');assert.equal(response.status(),200);checks++;
  await page.locator('.orgHeroPhoto img').waitFor();await page.locator('.orgHeroPhoto img').evaluate(image=>image.decode());
  assert.equal(await page.locator('h1').innerText(),title);assert.equal(await page.locator('.orgService').count(),1);assert.match(await page.locator('.orgService').innerText(),/1\s200 тест\. ₽/);assert.equal(await page.locator('.orgMark img').count(),0);assert.equal(await page.locator('.orgPhotoNote').innerText(),'Фото направления');assert.equal(await page.evaluate(()=>window.publicXss),undefined);checks+=6;
  for(const privateText of ['PRIVATE BUSINESS DESCRIPTION','PRIVATE CLIENT','private@example.test','PRIVATE HEALTH NOTE']){assert.equal((await page.content()).includes(privateText),false);checks++}
  for(const width of [320,375,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Overflow '+width+' '+colorScheme);
   const photo=page.locator('.orgHeroPhoto');assert.ok((await photo.boundingBox()).height>=250);assert.equal(await page.locator('.orgHeroPhoto img').evaluate(image=>image.complete&&image.naturalWidth>0),true);checks+=3;
  }
  await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({colorScheme:'light'});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'public-organization-visual-desktop.png'),fullPage:true});
  await page.setViewportSize({width:375,height:844});await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'public-organization-visual-mobile-dark.png'),fullPage:true});
  await page.locator('.orgActions [href="#orgContacts"]').click();assert.equal(await page.locator('.orgContacts').isVisible(),true);checks++;
  await page.goto(base+'/organizations/public-photo-empty');await page.locator('.orgHeroPhoto img').evaluate(image=>image.decode());assert.equal(await page.locator('.orgService').count(),0);assert.equal(await page.locator('.orgContacts').count(),0);assert.equal(await page.locator('[href="#orgContacts"]').count(),0);assert.match(await page.locator('.orgEmpty').innerText(),/Пока нет опубликованных услуг/);assert.match(await page.locator('.orgHeroPhoto img').getAttribute('src'),/foreman/);checks+=5;
  await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.tagName),'A');checks++;
  await page.route('**/assets/trainer-*.webp',route=>route.abort());
  await page.goto(base+'/organizations/public-photo-trainer');
  const fallback=page.locator('.orgHeroPhoto.hpPhotoUnavailable');await fallback.waitFor();
  assert.equal(await fallback.locator('img').count(),0);assert.equal(await fallback.getAttribute('role'),'img');assert.match(await fallback.getAttribute('aria-label'),/тренер/i);assert.match(await fallback.evaluate(frame=>getComputedStyle(frame,'::after').content),/H·Point/);checks+=4;
  for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);assert.ok((await fallback.boundingBox()).height>=250);checks+=2}
  await page.locator('.orgActions [href="#orgServices"]').click();assert.equal(await page.evaluate(()=>location.hash),'#orgServices');assert.equal(await page.locator('.orgService').count(),1);checks+=2;
  await page.locator('.orgService [href="#orgContacts"]').click();assert.equal(await page.evaluate(()=>location.hash),'#orgContacts');assert.equal(await page.locator('.orgContacts').isVisible(),true);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,localImages:true,publicAllowlist:true,responsiveThemes:true,emptyUseful:true,failedPhotoFallback:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
