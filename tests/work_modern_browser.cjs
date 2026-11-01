/* Modern work desk: real local records, search, scopes, filters, navigation and calendar. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {emailLogin}=require('./email_browser_login.cjs'),{workTab}=require('./work_browser_navigation.cjs');
const base=process.env.HPOINT_QA_URL,output=process.env.HPOINT_QA_OUTPUT;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable localhost only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'}),errors=[],external=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():(external.push(route.request().url()),route.abort()));
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 const get=async route=>{const response=await context.request.get(base+route);assert.equal(response.status(),200,await response.text());return response.json()};
 const post=async(route,data)=>{const response=await context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 const host=page.locator('#commercialWorkspace'),search=()=>host.locator('[data-work-search]'),record=(type,id)=>host.locator('[data-work-record="'+type+':'+id+'"]');
 const when=(days,hour)=>{const date=new Date();date.setDate(date.getDate()+days);date.setHours(hour,0,0,0);return date.toISOString()};
 try{
  await emailLogin(page,'theme-browser-data');await post('/api/commercial/profile',{kind:'foreman',title:'Тестовая команда порядка',description:'Проверка рабочего дня'});
  await post('/api/commercial/clients',{name:'Алёна Петрова',contact:'alena@example.test',notes:'Ключи у консьержа',active:true});await post('/api/commercial/clients',{name:'Архивный заказчик',active:false});
  let data=(await get('/api/commercial')).commercial;const client=data.clients.find(row=>row.active).id,archived=data.clients.find(row=>!row.active).id;
  await post('/api/commercial/services',{title:'Осмотр помещения',description:'План работ и рекомендации',price_rub:1500,duration_minutes:60,active:true});
  await post('/api/commercial/objects',{title:'Кухня на Лесной',address:'Синтетический адрес',status:'active',client_id:client,budget_rub:25000,actual_rub:500,ends_on:'2020-01-01'});
  await post('/api/commercial/tasks',{title:'Просроченный замер',notes:'Проверить размеры',status:'todo',due_at:when(-1,10),assignee_id:901});
  await post('/api/commercial/tasks',{title:'Задача без ответственного',status:'in_progress'});
  await post('/api/commercial/bookings',{client_id:client,title:'Сегодня: встреча с клиентом',starts_at:when(0,15),duration_minutes:60,price_rub:1500,status:'planned',assignee_id:901});
  await post('/api/commercial/bookings',{client_id:client,title:'Через три дня: продолжение',starts_at:when(3,15),duration_minutes:60,price_rub:2000,status:'planned'});
  await post('/api/commercial/bookings',{client_id:client,title:'Старая запись без результата',starts_at:when(-3,12),duration_minutes:60,price_rub:500,status:'planned'});
  await post('/api/commercial/shifts',{title:'Утренняя смена',starts_at:when(0,9),ends_at:when(0,10),assignee_id:901});
  await post('/api/commercial/shifts',{title:'Ночная переходящая смена',starts_at:when(-1,22),ends_at:when(0,8),assignee_id:901});
  data=(await get('/api/commercial')).commercial;const todayId=data.bookings.find(row=>row.title.startsWith('Сегодня')).id,taskId=data.tasks.find(row=>row.title==='Просроченный замер').id;
  await page.evaluate(()=>hpointWorkspace.refresh());await page.goto(base+'/#/work');await host.locator('.commercialDayDesk').waitFor();
  assert.equal(await host.locator('.commercialAgendaLink').count(),3);assert.match(await host.locator('.commercialAttentionRow').allTextContents().then(rows=>rows.join(' ')),/Просроченный замер/);checks+=2;
  await host.getByRole('button',{name:'7 дней',exact:true}).click();assert.equal(await host.locator('.commercialAgendaLink').count(),4);checks++;
  await host.getByRole('button',{name:'Мои дела',exact:true}).click();assert.equal(await host.locator('.commercialAgendaLink').count(),3);assert.equal(await host.locator('.commercialAttentionRow').filter({hasText:'Кухня на Лесной'}).count(),0);checks+=2;
  await host.getByRole('button',{name:'Мои дела',exact:true}).click();await host.getByRole('button',{name:'Сегодня',exact:true}).click();
  await host.locator('.commercialAttentionRow').filter({hasText:'Просроченный замер'}).click();await record('task',taskId).waitFor();assert.equal(await record('task',taskId).evaluate(node=>document.activeElement===node),true);assert.match(page.url(),/\/tasks$/);checks+=2;
  // Search resolves ё/е and opens the exact record while keeping an unrelated task draft.
  await host.locator('[data-commercial-form="tasks"] [name=title]').fill('Несохранённая задача');await search().fill('алена');assert.equal(await host.locator('.commercialSearchResult[data-type=client]').count(),1);await search().press('Enter');
  assert.equal(await record('client',client).evaluate(node=>document.activeElement===node),true);assert.equal(await host.locator('.commercialSearchResults').isVisible(),false);checks+=2;
  await workTab(page,'Задачи');assert.equal(await host.locator('[data-commercial-form="tasks"] [name=title]').inputValue(),'Несохранённая задача');checks++;
  await host.locator('[data-work-list-query]').fill('неизвестно');assert.equal(await host.locator('[data-work-list-empty]').isVisible(),true);assert.equal(await record('task',taskId).isVisible(),false);checks+=2;
  await host.getByRole('button',{name:'Сбросить',exact:true}).click();await host.locator('[data-work-list-person]').selectOption('unassigned');assert.equal(await host.locator('[data-work-record]:visible').count(),1);assert.match(await host.locator('[data-work-record]:visible').innerText(),/без ответственного/);checks+=2;
  await workTab(page,'Клиенты');await host.locator('[data-work-list-status]').selectOption('archived');assert.equal(await record('client',archived).isVisible(),true);assert.equal(await record('client',client).isVisible(),false);checks+=2;
  await search().fill('алена');await host.locator('.commercialSearchResult[data-type=client]').click();assert.equal(await record('client',client).isVisible(),true);assert.equal(await host.locator('[data-work-list-status]').inputValue(),'');checks+=2;
  await record('client',client).locator('.commercialClientHistory>summary').click();assert.equal(await record('client',client).locator('.professionalRecent').count(),3);await record('client',client).getByRole('button',{name:'Записать',exact:true}).click();assert.equal(await host.locator('[data-commercial-form=bookings] [name=client_id]').inputValue(),String(client));checks+=2;await workTab(page,'Услуги');page.once('dialog',dialog=>dialog.accept());await host.getByRole('button',{name:'Создать запись',exact:true}).click();assert.equal(await host.locator('[data-commercial-form=bookings] [name=title]').inputValue(),'Осмотр помещения');assert.equal(await host.locator('[data-commercial-form=bookings] [name=price_rub]').inputValue(),'1500');checks+=2;
  await page.keyboard.press('Control+k');assert.equal(await search().evaluate(node=>node===document.activeElement),true);await search().fill('ключи');assert.equal(await host.locator('.commercialSearchResult').count(),1);await search().press('Escape');assert.equal(await search().inputValue(),'');checks+=3;
  await search().fill('Сегодня: встреча');await host.locator('.commercialSearchResult').click();assert.equal(await record('booking',todayId).evaluate(node=>node===document.activeElement),true);checks++;
  await host.locator('[name=filter_status]').selectOption('planned');await host.getByRole('button',{name:'График команды',exact:true}).click();assert.equal(await host.locator('[data-work-record^="shift:"]').count(),2);checks++;
  // Selecting a day includes work crossing midnight, just like the overview and calendar.
  const today=await page.evaluate(()=>{const d=new Date();return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,10)});
  await host.locator('[name=filter_date]').fill(today);assert.equal(await host.locator('[data-work-record^="shift:"]').count(),2);assert.match(await host.locator('[data-work-record^="shift:"]').allTextContents().then(rows=>rows.join(' ')),/Ночная переходящая смена/);checks+=2;
  await host.getByRole('button',{name:'Записи и заказы',exact:true}).click();assert.equal(await host.locator('[data-work-record^="booking:"]').count(),1);checks++;await host.locator('[name=filter_date]').fill('');
  // Calendar is an explicit file copy, correctly scoped to the active schedule.
  const downloaded=page.waitForEvent('download');await host.getByRole('button',{name:'В календарь (.ics)',exact:true}).click();const file=await downloaded;assert.equal(await file.failure(),null);const target=path.join(output,'modern-work-calendar.ics');await file.saveAs(target);const calendar=fs.readFileSync(target,'utf8');assert.match(calendar,/BEGIN:VCALENDAR/);assert.match(calendar,/Сегодня: встреча/);assert.doesNotMatch(calendar,/ключи|alena@example.test|Ключи/);checks+=4;
  // A manual reload reports failure without switching organisations or dropping drafts.
  await host.locator('[data-commercial-form="bookings"] [name=title]').fill('Черновик после обновления');const transient=route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'Проверочная недоступность'})});await context.route('**/api/commercial?*',transient);
  await host.getByRole('button',{name:'Обновить данные кабинета',exact:true}).click();await host.getByRole('alert').waitFor();assert.equal(await host.locator('[data-commercial-form="bookings"] [name=title]').inputValue(),'Черновик после обновления');assert.match(await host.getByRole('alert').innerText(),/Проверочная недоступность/);checks+=2;await context.unroute('**/api/commercial?*',transient);
  await host.getByRole('button',{name:'Обновить данные кабинета',exact:true}).click();await host.getByRole('alert').waitFor({state:'detached'});checks++;
  // Text typed while an explicit reload is in flight must survive the response.
  let releaseReload,announceReload;const reloadGate=new Promise(resolve=>releaseReload=resolve),reloadSeen=new Promise(resolve=>announceReload=resolve),delayedReload=async route=>{announceReload();await reloadGate;await route.continue()};await context.route('**/api/commercial?*',delayedReload);const pendingReload=page.evaluate(()=>hpointCommercial.refresh());await reloadSeen;await host.locator('[data-commercial-form=bookings] [name=title]').fill('Введено во время загрузки');releaseReload();await pendingReload;assert.equal(await host.locator('[data-commercial-form=bookings] [name=title]').inputValue(),'Введено во время загрузки');checks++;await context.unroute('**/api/commercial?*',delayedReload);
  // Responsive views: no horizontally hidden controls, same useful overview on a phone.
  await workTab(page,'Обзор');for(const theme of ['light','dark'])for(const width of [320,360,390,768,1024,1440]){await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Outer '+width+' '+theme);assert.equal(await host.locator('.commercialContent').evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,'Inner '+width+' '+theme);checks+=2;if(width===390||width===1440){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,'modern-work-overview-'+width+'-'+theme+'.png'),fullPage:true})}}
  await page.setViewportSize({width:390,height:1000});await workTab(page,'Клиенты');assert.equal(await host.locator('.commercialNavToggle').getAttribute('aria-expanded'),'false');await host.locator('[data-work-list-query]').fill('Алёна');await page.screenshot({path:path.join(output,'modern-work-clients-mobile.png'),fullPage:true});checks++;
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);checks+=2;console.log(JSON.stringify({ok:true,checks,dayDesk:true,searchJump:true,drafts:true,listFilters:true,calendar:true,responsive:true,errors,external}));
 }catch(error){console.error('Work UI:',await host.innerText().catch(()=>''));console.error(errors);await page.screenshot({path:path.join(output,'modern-work-failure.png'),fullPage:true}).catch(()=>{});throw error}finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
