/* Professional records: useful filters, linked creation and stable drafts. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs'),{workTab,openEditor}=require('./work_browser_navigation.cjs');
const base=process.env.HPOINT_QA_URL;if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable localhost only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),page=await context.newPage(),errors=[];let checks=0;
 page.on('pageerror',error=>errors.push(error.message));await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const post=async(route,data)=>{const response=await context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 const get=async()=>{const response=await context.request.get(base+'/api/commercial');assert.equal(response.status(),200,await response.text());return (await response.json()).commercial};
 const records=()=>page.locator('.professionalRecord:visible'),record=id=>page.locator('[data-professional-record="'+id+'"]');
 try{
  await emailLogin(page,'theme-browser-data');await post('/api/commercial/profile',{kind:'repair',title:'Проверка рабочего ритма'});await post('/api/commercial/clients',{name:'Нина',active:true});let data=await get();
  for(const title of ['Ноутбук Нины','Принтер'])await post('/api/commercial/professional/equipment',{title,client_id:data.clients[0].id,status:'active'});
  data=await get();const equipment=data.professional.modules.find(module=>module.key==='equipment').records,notebook=equipment.find(row=>row.title==='Ноутбук Нины'),printer=equipment.find(row=>row.title==='Принтер');
  const today=await page.evaluate(()=>{const d=new Date();return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,10)}),yesterday=new Date(today+'T12:00:00Z');yesterday.setUTCDate(yesterday.getUTCDate()-1);const past=yesterday.toISOString().slice(0,10);
  for(const row of [{title:'Экран',equipment_id:notebook.id,due_on:past,status:'in_progress'},{title:'Диагностика',equipment_id:printer.id,due_on:today,status:'received'},{title:'Выданный ремонт',equipment_id:notebook.id,due_on:past,status:'delivered'}])await post('/api/commercial/professional/repair_orders',{...row,received_on:past});
  await page.evaluate(()=>hpointWorkspace.refresh());await page.goto(base+'/#/work');await workTab(page,'professional:repair_orders');
  assert.equal(await records().count(),2);assert.match(await page.locator('[data-professional-count]').innerText(),/2 из 3/);assert.equal(await page.locator('.professionalDue:visible').count(),1);checks+=3;
  await page.locator('[data-professional-search]').fill('ноутбук');assert.equal(await records().count(),1);assert.match(await records().innerText(),/Экран/);checks+=2;
  await workTab(page,'overview');await workTab(page,'professional:repair_orders');assert.equal(await page.locator('[data-professional-search]').inputValue(),'ноутбук');assert.equal(await records().count(),1);checks+=2;
  await page.locator('[data-professional-clear]').click();await page.locator('.professionalAdvancedFilters>summary').click();await page.locator('[data-professional-date-filter]').selectOption('today');assert.equal(await records().count(),1);assert.match(await records().innerText(),/Диагностика/);checks+=2;
  await page.locator('[data-professional-date-filter]').selectOption('overdue');assert.equal(await records().count(),1);assert.match(await records().innerText(),/Экран/);checks+=2;
  await page.locator('[data-professional-date-filter]').selectOption('');await page.locator('[data-professional-status-filter]').selectOption('all');await page.locator('[data-professional-reference-filter]').selectOption(String(notebook.id));assert.equal(await records().count(),2);checks++;
  await page.locator('[data-professional-sort]').selectOption('title');assert.match(await records().first().innerText(),/Выданный ремонт/);checks++;
  await page.locator('[data-professional-clear]').click();assert.equal(await records().count(),2);assert.equal(await page.locator('[data-professional-clear]').isVisible(),false);checks+=2;
  // Changing a record status must not discard a composed professional form.
  await openEditor(page,'professional/repair_orders');const form=page.locator('[data-commercial-form="professional/repair_orders"]');await form.locator('[name=title]').fill('Несохранённый ремонт');await form.locator('[name=equipment_id]').selectOption(String(notebook.id));
  const diagnosis=(await get()).professional.modules.find(module=>module.key==='repair_orders').records.find(row=>row.title==='Диагностика');await record(diagnosis.id).locator('[data-commercial-action="professional-status"][data-status="diagnostics"]').click();await page.waitForFunction(()=>!document.querySelector('#commercialWorkspace button[type=submit]:disabled'));assert.equal(await form.locator('[name=title]').inputValue(),'Несохранённый ремонт');assert.equal(await form.locator('[name=equipment_id]').inputValue(),String(notebook.id));checks+=2;
  // Search can reveal a terminal record hidden by the default current filter.
  const delivered=(await get()).professional.modules.find(module=>module.key==='repair_orders').records.find(row=>row.status==='delivered');await page.evaluate(id=>HPointProfessional.reveal(document.querySelector('#commercialWorkspace'),'repair_orders',id),delivered.id);assert.equal(await record(delivered.id).isVisible(),true);assert.equal(await record(delivered.id).evaluate(node=>document.activeElement===node),true);checks+=2;
  await workTab(page,'professional:equipment');await record(notebook.id).locator('.professionalRecordMore>summary').click();page.once('dialog',dialog=>dialog.dismiss());await record(notebook.id).locator('[data-commercial-action="professional-new"]').click();await workTab(page,'professional:repair_orders');assert.equal(await form.locator('[name=title]').inputValue(),'Несохранённый ремонт');checks++;
  await workTab(page,'professional:equipment');await record(notebook.id).locator('.professionalRecordMore>summary').click();page.once('dialog',dialog=>dialog.accept());await record(notebook.id).locator('[data-commercial-action="professional-new"]').click();assert.equal(await form.locator('[name=equipment_id]').inputValue(),String(notebook.id));assert.equal(await form.locator('[name=title]').inputValue(),'');checks+=2;
  // View memory is scoped to the organisation; no names/filters leak to another.
  const isolated=await page.evaluate(async()=>{const d=(await(await fetch('/api/commercial')).json()).commercial;d.selected_owner_id=999999;return HPointProfessional.render(d,'repair_orders')});assert.match(isolated,/data-professional-search value=""/);checks++;
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);checks++}
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,linkedSearch:true,dateAndReferenceFilters:true,stableViews:true,stableDraftOnStatus:true,linkedCreation:true}));
 }catch(error){console.error(await page.locator('#commercialWorkspace').innerText().catch(()=>''));throw error}
 finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
