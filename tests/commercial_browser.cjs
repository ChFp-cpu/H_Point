/* Commercial workspace: disposable local email account, test funds only. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 const get=route=>context.request.get(base+route).then(r=>r.json());
 try{
  await emailLogin(page,'theme-browser-data');
  await page.waitForFunction(()=>Boolean(window.hpointCommercial));
  await page.evaluate(()=>hpointCommercial.open());
  await page.waitForURL('**/#/work');
  const host=page.locator('#commercialWorkspace');
  assert.equal(await page.locator('#commercialOverlay').count(),0);assert.equal(await page.locator('#hpointWorkPage').getAttribute('aria-labelledby'),'commercialTitle');checks+=2;
  const profile=host.locator('[data-commercial-form="profile"]');
  await profile.waitFor();await profile.locator('[name="kind"]').selectOption('trainer');
  await profile.locator('[name="title"]').fill('Тестовая студия движения');
  await profile.locator('[name="description"]').fill('Персональные занятия и группы');
  await profile.getByRole('button',{name:'Начать 7 бесплатных дней',exact:true}).click();
  await host.getByRole('heading',{name:'Тестовая студия движения',exact:true}).waitFor();
  const initial=(await get('/api/commercial')).commercial;
  assert.equal(initial.profile.active,true);assert.equal(initial.profile.trial_active,true);assert.equal(initial.profile.days_remaining,7);checks+=3;
  await host.locator('.commercialTabs').getByRole('button',{name:'Услуги',exact:true}).click();
  const service=host.locator('[data-commercial-form="services"]');
  await service.locator('[name="title"]').fill('Персональная тренировка');await service.locator('[name="price_rub"]').fill('700');await service.locator('[name="duration_minutes"]').fill('60');
  await service.locator('[name="description"]').fill('Синтетическая услуга для проверки');
  await service.getByRole('button',{name:'Добавить услугу',exact:true}).click();
  await host.locator('.commercialRow').getByText('Персональная тренировка',{exact:true}).waitFor();checks++;
  await host.locator('.commercialTabs').getByRole('button',{name:'Клиенты',exact:true}).click();
  const client=host.locator('[data-commercial-form="clients"]');
  await client.locator('[name="name"]').fill('Тестовый клиент');await client.locator('[name="contact"]').fill('Контакт предоставлен клиентом');await client.locator('[name="notes"]').fill('Первая встреча; только тестовые данные');
  await client.getByRole('button',{name:'Добавить клиента',exact:true}).click();
  await host.locator('.commercialRow').getByText('Тестовый клиент',{exact:true}).waitFor();checks++;
  await host.locator('.commercialTabs').getByRole('button',{name:'Расписание',exact:true}).click();
  const booking=host.locator('[data-commercial-form="bookings"]');
  await booking.locator('[name="client_id"]').selectOption({label:'Тестовый клиент'});await booking.locator('[name="service_id"]').selectOption({label:'Персональная тренировка'});
  assert.equal(await booking.locator('[name="title"]').inputValue(),'Персональная тренировка');assert.equal(await booking.locator('[name="price_rub"]').inputValue(),'700');checks+=2;
  await booking.locator('[name="starts_at"]').fill('2030-02-01T12:00');await booking.locator('[name="notes"]').fill('Уточнить удобное время');
  await booking.getByRole('button',{name:'Добавить запись',exact:true}).click();
  const row=host.locator('.commercialRow').filter({hasText:'Персональная тренировка'});
  await row.getByRole('button',{name:'Выполнено',exact:true}).waitFor();
  await row.getByRole('button',{name:'Выполнено',exact:true}).click();
  await host.locator('.commercialTag').filter({hasText:'Выполнено'}).waitFor();
  const completed=(await get('/api/commercial')).commercial;
  assert.equal(completed.metrics.completed,1);assert.equal(completed.metrics.planned,0);assert.equal(completed.metrics.revenue_test_rub,700);checks+=3;
  await host.locator('.commercialTabs').getByRole('button',{name:'Обзор',exact:true}).click();
  assert.match(await host.innerText(),/700 тест\. ₽/);checks++;
  const walletBefore=(await get('/api/wallet')).wallet;
  assert.ok(walletBefore.test_balance_rub>=490,'QA seed must provide test funds');
  page.once('dialog',dialog=>dialog.accept());await host.getByRole('button',{name:'Продлить на 30 дней · 490 тест. ₽',exact:true}).click();
  await page.waitForFunction(async()=>{let d=await fetch('/api/commercial').then(r=>r.json());return d.commercial.renewals.length===1});
  const renewed=(await get('/api/commercial')).commercial,walletAfter=(await get('/api/wallet')).wallet;
  assert.equal(walletBefore.test_balance_rub-walletAfter.test_balance_rub,490);assert.equal(renewed.renewals[0].price_rub,490);checks+=2;
  // The dedicated page supports both themes and narrow phones.
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({colorScheme});
   const colors=await host.evaluate(el=>{const s=getComputedStyle(el);return {text:s.color,background:s.backgroundColor}});
   const luminance=color=>{let rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(c=>{c/=255;return c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4)});return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
   const a=luminance(colors.text),b=luminance(colors.background);assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,'Readable commercial workspace in '+colorScheme);checks++;
   for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++}
   await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'commercial-'+colorScheme+'.png'),fullPage:false});
  }
  await page.goto(base+'/#/home');await page.evaluate(()=>hpointWorkspace.refresh());await page.locator('.homeWorkSummary').waitFor();assert.match(await page.locator('.homeWorkSummary').innerText(),/Тестовая студия движения/);checks++;
  await page.locator('.homeWorkSummary').getByRole('button',{name:'Открыть «Для работы» →',exact:true}).click();await host.getByRole('heading',{name:'Тестовая студия движения',exact:true}).waitFor();checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,commercialTrialAndRenewal:true,servicesClientsBookings:true}));
 }catch(error){console.error('Commercial UI:',await page.locator('#commercialWorkspace').innerText().catch(()=>''));console.error('Browser errors:',errors);await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'commercial-failure.png'),fullPage:true}).catch(()=>{});throw error}finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
