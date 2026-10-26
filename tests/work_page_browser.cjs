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
  const navigation=await page.locator('#sitePrimaryNav [data-route]').evaluateAll(nodes=>nodes.map(e=>e.dataset.route));assert.deepEqual(navigation,['home','help','work','activities']);checks++;
  await page.locator('#sitePrimaryNav [data-route="work"]').click();
  await page.waitForURL('**/#/work');await page.locator('#hpointWorkPage').getByRole('heading',{name:'Для работы',exact:true}).waitFor();
  assert.equal(await page.locator('#commercialOverlay,[aria-modal="true"]#hpointWorkPage').count(),0);
  assert.equal(await page.locator('#hpointWorkPage').evaluate(e=>getComputedStyle(e).position==='fixed'),false);checks+=2;
  const host=page.locator('#commercialWorkspace'),profile=host.locator('[data-commercial-form="profile"]');
  await profile.locator('[name="kind"]').selectOption('organization');await profile.locator('[name="title"]').fill('Тестовая организация');
  await profile.getByRole('button',{name:'Начать 7 бесплатных дней',exact:true}).click();await host.getByRole('heading',{name:'Тестовая организация',exact:true}).waitFor();checks++;
  await host.locator('.commercialTabs').getByRole('button',{name:'Услуги',exact:true}).click();
  const service=host.locator('[data-commercial-form="services"]');await service.locator('[name="title"]').fill('Услуга для организации');
  await service.locator('[name="price_rub"]').fill('900');
  await service.locator('[name="description"]').fill('Черновик сохраняется при обновлении');
  await service.locator('[name="description"]').focus();await service.locator('[name="description"]').evaluate(e=>e.setSelectionRange(4,10));
  await service.evaluate(e=>window.qaWorkForm=e);await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await service.evaluate(e=>e===window.qaWorkForm),true);assert.equal(await service.locator('[name="description"]').inputValue(),'Черновик сохраняется при обновлении');checks+=2;
  assert.deepEqual(await service.locator('[name="description"]').evaluate(e=>({focused:document.activeElement===e,start:e.selectionStart,end:e.selectionEnd})),{focused:true,start:4,end:10});checks++;
  await service.getByRole('button',{name:'Добавить услугу',exact:true}).click();await host.locator('.commercialRow').getByText('Услуга для организации',{exact:true}).waitFor();
  await host.locator('.commercialTabs').getByRole('button',{name:'Клиенты',exact:true}).click();
  const client=host.locator('[data-commercial-form="clients"]');await client.locator('[name="name"]').fill('Тестовый клиент организации');await client.locator('[name="contact"]').fill('Секретный контакт');await client.getByRole('button',{name:'Добавить клиента',exact:true}).click();await host.locator('.commercialRow').getByText('Тестовый клиент организации',{exact:true}).waitFor();
  await host.locator('.commercialTabs').getByRole('button',{name:'Расписание',exact:true}).click();
  const booking=host.locator('[data-commercial-form="bookings"]');await booking.locator('[name="client_id"]').selectOption({label:'Тестовый клиент организации'});await booking.locator('[name="service_id"]').selectOption({label:'Услуга для организации'});await booking.locator('[name="starts_at"]').fill('2030-02-01T12:00');await booking.getByRole('button',{name:'Добавить запись',exact:true}).click();await host.locator('.commercialRow').getByText('Услуга для организации',{exact:true}).waitFor();
  assert.equal(new URL(page.url()).hash,'#/work');assert.equal(await host.locator('[data-commercial-action="community"]').count(),0);checks+=2;
  await host.locator('.commercialTabs').getByRole('button',{name:'Подписка',exact:true}).click();await host.getByRole('heading',{name:'Подписка для работы',exact:true}).waitFor();assert.equal(new URL(page.url()).hash,'#/work');checks++;
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
  await host.getByRole('heading',{name:'Откройте свой кабинет',exact:true}).waitFor();assert.doesNotMatch(await host.innerText(),/Тестовая организация|Секретный контакт/);assert.deepEqual((await get('/api/commercial/summary')).summary,{exists:false});checks+=2;
  await post('/api/auth/login',{email:'qa901@example.test',password:'SyntheticQa1'});await page.evaluate(()=>hpointWorkspace.refresh());await host.getByRole('heading',{name:'Тестовая организация',exact:true}).waitFor();checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,dedicatedWorkPage:true,privateHomeSummary:true,stableWorkForms:true,accountSwitchSafe:true}));
 }catch(error){console.error('Work UI:',await page.locator('#commercialWorkspace').innerText().catch(()=>''));console.error('Browser errors:',errors);await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'work-page-failure.png'),fullPage:true}).catch(()=>{});throw error}finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
