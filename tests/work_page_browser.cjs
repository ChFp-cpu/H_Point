const {workTab}=require('./work_browser_navigation.cjs');
/* Dedicated work page and private home overview; synthetic email accounts. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 async function get(url){const response=await context.request.get(base+url);assert.equal(response.status(),200,await response.text());return response.json()}
 async function post(url,data){const response=await context.request.post(base+url,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 try{
  await emailLogin(page,'theme-browser-data');
  assert.deepEqual((await get('/api/commercial/summary')).summary,{exists:false});
  await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await page.locator('.homeWorkSummary').count(),0);checks+=2;
  const navigation=await page.locator('#sitePrimaryNav [data-route]').evaluateAll(nodes=>nodes.map(e=>e.dataset.route));assert.deepEqual(navigation,['home','help','activities']);checks++;
  await page.evaluate(()=>go('profile'));
  await page.locator('#workspaceWorkCreationSlot').getByRole('button',{name:'Создать кабинет в профиле',exact:true}).click();
  await page.waitForURL('**/#/profile');
  assert.equal(await page.locator('#commercialOverlay,[aria-modal="true"]#hpointWorkPage').count(),0);
  assert.equal(await page.locator('#hpointWorkPage').evaluate(e=>getComputedStyle(e).position==='fixed'),false);checks+=2;
  const host=page.locator('#commercialWorkspace'),profile=host.locator('[data-commercial-form="profile"]');
  await profile.locator('[name="kind"]').selectOption('organization');await profile.locator('[name="title"]').fill('Тестовая организация');
  await profile.locator('[name="contact"]').press('Enter');await page.waitForURL('**/#/work');await host.getByRole('heading',{name:'Тестовая организация',exact:true}).waitFor();await page.evaluate(()=>hpointWorkspace.refresh());await page.locator('#sitePrimaryNav [data-route="work"]').waitFor();assert.equal(await page.locator('#sitePrimaryNav [data-route="work"]').count(),1);checks+=2;
  await workTab(page,'Услуги');
  const service=host.locator('[data-commercial-form="services"]');await service.locator('[name="title"]').fill('Услуга для организации');
  await service.locator('[name="price_rub"]').fill('900');
  await service.locator('[name="description"]').fill('Черновик сохраняется при обновлении');
  await service.locator('[name="description"]').focus();await service.locator('[name="description"]').evaluate(e=>e.setSelectionRange(4,10));
  await service.evaluate(e=>window.qaWorkForm=e);await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await service.evaluate(e=>e===window.qaWorkForm),true);assert.equal(await service.locator('[name="description"]').inputValue(),'Черновик сохраняется при обновлении');checks+=2;
  assert.deepEqual(await service.locator('[name="description"]').evaluate(e=>({focused:document.activeElement===e,start:e.selectionStart,end:e.selectionEnd})),{focused:true,start:4,end:10});checks++;
  await service.getByRole('button',{name:'Добавить услугу',exact:true}).click();await host.locator('.commercialRow').getByText('Услуга для организации',{exact:true}).waitFor();
  await workTab(page,'Клиенты');
  const client=host.locator('[data-commercial-form="clients"]');await client.locator('[name="name"]').fill('Тестовый клиент организации');await client.locator('[name="contact"]').fill('Секретный контакт');await client.getByRole('button',{name:'Добавить клиента',exact:true}).click();await host.locator('.commercialRow').getByText('Тестовый клиент организации',{exact:true}).waitFor();
  await workTab(page,'Расписание');
  const booking=host.locator('[data-commercial-form="bookings"]');await booking.locator('[name="client_id"]').selectOption({label:'Тестовый клиент организации'});await booking.locator('[name="service_id"]').selectOption({label:'Услуга для организации'});await booking.locator('[name="starts_at"]').fill('2030-02-01T12:00');await booking.getByRole('button',{name:'Добавить запись',exact:true}).click();await host.locator('.commercialRow').getByText('Услуга для организации',{exact:true}).waitFor();
  assert.equal(new URL(page.url()).hash,'#/work/901/bookings');assert.equal(await host.locator('[data-commercial-action="community"]').count(),0);checks+=2;
  await workTab(page,'Подписка');await host.getByRole('heading',{name:'Подписка для работы',exact:true}).waitFor();assert.equal(new URL(page.url()).hash,'#/work/901/subscription');checks++;
  await page.locator('#sitePrimaryNav [data-route="home"]').click();await page.evaluate(()=>hpointWorkspace.refresh());
  await page.locator('.homeWorkSummary').waitFor();const summary=(await get('/api/commercial/summary')).summary;
  assert.equal(summary.title,'Тестовая организация');assert.equal(summary.metrics.planned,1);assert.equal(summary.next_appointments.length,1);assert.doesNotMatch(JSON.stringify(summary),/Секретный контакт/);assert.match(await page.locator('.homeWorkSummary').innerText(),/Услуга для организации/);checks+=5;
  await page.locator('.homeWorkSummary').getByRole('button',{name:'Открыть «Для работы» →',exact:true}).click();await page.waitForURL('**/#/work');
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++}
   await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'work-page-'+colorScheme+'.png'),fullPage:true});
  }
  // Switching accounts within the same JS runtime must clear the old page.
  await post('/api/auth/login',{email:'qa904@example.test',password:'SyntheticQa1'});await page.evaluate(()=>hpointWorkspace.refresh());
  await host.getByRole('heading',{name:'Создайте кабинет в профиле',exact:true}).waitFor();assert.doesNotMatch(await host.innerText(),/Тестовая организация|Секретный контакт/);assert.deepEqual((await get('/api/commercial/summary')).summary,{exists:false});checks+=2;
  await post('/api/auth/login',{email:'qa901@example.test',password:'SyntheticQa1'});await page.evaluate(()=>hpointWorkspace.refresh());await host.getByRole('heading',{name:'Тестовая организация',exact:true}).waitFor();checks++;
  const original=(await get('/api/commercial')).commercial.profile;
  await workTab(page,'Настройки');
  page.once('dialog',dialog=>dialog.dismiss());await host.getByRole('button',{name:'Удалить компанию',exact:true}).click();
  assert.equal((await get('/api/commercial/summary')).summary.exists,true);checks++;
  page.once('dialog',dialog=>dialog.accept());await host.getByRole('button',{name:'Удалить компанию',exact:true}).click();
  await page.waitForURL('**/#/profile');await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.locator('#sitePrimaryNav [data-route="work"]').count(),0);assert.equal((await get('/api/commercial/summary')).summary.exists,false);checks+=2;
  const deleted=(await get('/api/commercial')).commercial;assert.equal(deleted.profile,null);assert.deepEqual(deleted.clients,[]);assert.deepEqual(deleted.services,[]);assert.deepEqual(deleted.bookings,[]);assert.equal(deleted.trial_available,false);checks+=5;
  await page.locator('#workspaceWorkCreationSlot').getByRole('button',{name:'Создать кабинет в профиле',exact:true}).click();
  const recreated=host.locator('[data-commercial-form="profile"]');assert.equal(await recreated.getByRole('button',{name:'Начать 7 бесплатных дней',exact:true}).count(),0);await recreated.locator('[name="kind"]').selectOption('organization');await recreated.locator('[name="title"]').fill('Новая тестовая компания');await recreated.locator('[name="contact"]').press('Enter');await page.waitForURL('**/#/work');
  const restored=(await get('/api/commercial')).commercial.profile;assert.equal(restored.trial_until,original.trial_until);assert.equal(restored.trial_started_at,original.trial_started_at);checks+=3;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,dedicatedWorkPage:true,privateHomeSummary:true,stableWorkForms:true,accountSwitchSafe:true}));
 }catch(error){const sync=await context.request.get(base+'/api/sync');const diagnostic=await sync.json().catch(()=>({}));console.error('Sync diagnostic:',JSON.stringify({status:sync.status(),ok:diagnostic.ok,error:diagnostic.error,userPresent:Boolean(diagnostic.user)}));console.error('Work UI:',await page.locator('#commercialWorkspace').innerText().catch(()=>''));console.error('Browser errors:',errors);await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'work-page-failure.png'),fullPage:true}).catch(()=>{});throw error}finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
