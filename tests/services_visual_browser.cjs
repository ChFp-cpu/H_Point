/* Real published services, photograph labels and responsive category filtering. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket){const context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light',reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));await emailLogin(page,ticket);return {context,page}}
 async function post(actor,endpoint,data){const response=await actor.context.request.post(base+endpoint,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 async function reload(page){await page.evaluate(()=>{hpointOrganizations.invalidate();hpointOrganizations.mount(document.getElementById('workspaceServiceDirectory'))})}
 try{
  const owner=await actor('theme-browser-data'),other=await actor('mobile-helper'),page=owner.page;
  await page.goto(base+'/#/activities');await page.locator('.activityDirectory').waitFor();await page.locator('.servicesEmpty h3').waitFor();
  assert.equal(await page.locator('.activityService').count(),0);assert.match(await page.locator('.servicesEmpty').innerText(),/Оформите рабочий кабинет/);assert.equal(await page.locator('[data-service-category]').count(),9);checks+=3;
  await page.locator('[data-service-category=trainer]').click();assert.match(await page.locator('.servicesEmpty').innerText(),/другое направление/);await page.locator('.servicesEmpty [data-services-reset]').click();checks++;
  const title='Подготовка к любительским соревнованиям и восстановительная тренировка';
  await post(owner,'/api/commercial/profile',{kind:'trainer',title:'Тестовый тренер',description:'Синтетическая организация',contact:''});
  const trainer=(await post(owner,'/api/commercial/services',{title,description:'Личное занятие. <script>window.qaServiceXss=1</script>',price_rub:1200,duration_minutes:60})).result.id;
  await post(owner,'/api/commercial/services',{title:'Неопубликованная услуга',description:'PRIVATE UNPUBLISHED',price_rub:600,duration_minutes:30});
  await post(owner,'/api/commercial/public-profile',{slug:'visual-trainer',published:true,description:'Синтетическая публичная страница',contact:'',address:'Тестовый город'});
  await post(owner,'/api/commercial/services/publish',{id:trainer,published:true});
  await post(other,'/api/commercial/profile',{kind:'foreman',title:'Тестовая строительная команда',description:'Синтетическая организация',contact:''});
  const building=(await post(other,'/api/commercial/services',{title:'План ремонта и подготовка сметы',description:'Учёт материалов и этапов работ.',price_rub:2300,duration_minutes:90})).result.id;
  await post(other,'/api/commercial/public-profile',{slug:'visual-foreman',published:true,description:'Синтетическая публичная страница',contact:'',address:'Тестовый город'});
  await post(other,'/api/commercial/services/publish',{id:building,published:true});
  await reload(page);await page.waitForFunction(()=>document.querySelectorAll('.activityService').length===2);
  assert.equal(await page.locator('.activityServicePhotoNote').count(),2);assert.equal(await page.locator('.activityService').getByText('Неопубликованная услуга').count(),0);assert.equal(await page.evaluate(()=>window.qaServiceXss),undefined);assert.equal(await page.locator('.activityService script').count(),0);checks+=4;
  assert.equal(await page.locator('.activityService[data-service-kind=trainer]').count(),1);assert.equal(await page.locator('.activityService[data-service-kind=foreman]').count(),1);checks+=2;
  await page.locator('[data-service-category=trainer]').click();assert.equal(await page.locator('.activityService').count(),1);assert.match(await page.locator('.activityService').innerText(),/1\s?200 тест\. ₽/);assert.equal(await page.locator('.activityService a').getAttribute('href'),'/organizations/visual-trainer');checks+=3;
  await page.locator('[data-services-kind]').selectOption('foreman');assert.equal(await page.locator('.activityService').count(),1);assert.match(await page.locator('.activityService').innerText(),/План ремонта/);checks+=2;
  await page.locator('[data-services-reset-filter]').click();await page.getByRole('searchbox',{name:'Поиск услуг организаций'}).fill('Тестовый тренер');await page.locator('.activityServicesSearch').getByRole('button',{name:'Найти',exact:true}).click();assert.equal(await page.locator('.activityService').count(),1);checks++;
  await page.getByRole('searchbox',{name:'Поиск услуг организаций'}).fill('Нет такой услуги');await page.locator('.activityServicesSearch').getByRole('button',{name:'Найти',exact:true}).click();assert.equal(await page.locator('.activityService').count(),0);await page.locator('.servicesEmpty [data-services-reset]').click();assert.equal(await page.locator('.activityService').count(),2);checks+=2;
  await page.locator('.serviceCategoriesMore summary').click();
  for(const width of [320,375,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme});await page.locator('.activityDirectory').waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Overflow '+width+' '+colorScheme);assert.equal(await page.locator('.activityService').count(),2);checks+=2;
  }
  assert.ok(await page.locator('.serviceCategory img').count()>=9,'Nine photographed real professions');assert.equal(await page.locator('.activityServicePhoto img').count(),2);checks+=2;
  for(const image of await page.locator('#workspaceServiceDirectory .serviceCategory img,#workspaceServiceDirectory .activityServicePhoto img').all()){await image.scrollIntoViewIfNeeded();await image.evaluate(node=>node.decode());assert.equal(await image.evaluate(node=>node.complete&&node.naturalWidth>0),true,'Photograph must load');checks++}
  await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({colorScheme:'light'});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'services-visual-desktop.png'),fullPage:true});
  await page.setViewportSize({width:375,height:844});await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'services-visual-mobile-dark.png'),fullPage:true});
  await page.evaluate(()=>{const host=document.createElement('div');host.id='qaServicesPreview';document.getElementById('hpointWorkspace').appendChild(host);hpointOrganizations.mountPreview(host)});await page.locator('#qaServicesPreview .activityService').first().waitFor();assert.equal(await page.locator('#qaServicesPreview .activityService').count(),2);checks++;
  await post(owner,'/api/commercial/services/publish',{id:trainer,published:false});await reload(page);await page.waitForFunction(()=>document.querySelectorAll('#workspaceServiceDirectory .activityService').length===1);assert.match(await page.locator('#workspaceServiceDirectory .activityService').innerText(),/План ремонта/);checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,publishedOnly:true,truthfulCategoryImages:true,liveFilters:true,responsiveThemes:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
