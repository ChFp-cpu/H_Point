/* Real work-estimate editing and downloads, disposable localhost accounts only. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),{execFileSync}=require('node:child_process');
const {emailLogin}=require('./email_browser_login.cjs'),{workTab,openEditor}=require('./work_browser_navigation.cjs');
const base=process.env.HPOINT_QA_URL,output=process.env.HPOINT_QA_OUTPUT;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable localhost only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[],external=[],downloads=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():(external.push(route.request().url()),route.abort()));
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 const get=async route=>{const response=await context.request.get(base+route);assert.equal(response.status(),200,await response.text());return response.json()};
 const post=async(route,data)=>{const response=await context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 const form=()=>page.locator('[data-commercial-form="estimates"]');
 const saved=title=>page.locator('.estimateSavedList [data-estimate-id]').filter({has:page.getByRole('heading',{name:title,exact:true})});
 async function save(label='Добавить смету'){await form().getByRole('button',{name:label,exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#commercialWorkspace button[type=submit]:disabled'));assert.equal(await page.locator('.commercialError').count(),0,await page.locator('#commercialWorkspace').innerText());checks++}
 async function layout(label){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,label);assert.equal(await page.locator('.commercialContent').evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,label+' inner');checks+=2}
 async function download(row,label,extension){const ready=page.waitForEvent('download');await row.getByRole('button',{name:label,exact:true}).click();const file=await ready;assert.equal(await file.failure(),null);assert.ok(file.suggestedFilename().endsWith('.'+extension));const target=path.join(output,'work-estimate-'+downloads.length+'.'+extension);await file.saveAs(target);const bytes=fs.readFileSync(target);assert.ok(bytes.length>500);assert.ok(bytes.subarray(0,4).toString()===(extension==='pdf'?'%PDF':'PK\u0003\u0004'));downloads.push(target);checks+=4;return target}
 try{
  await emailLogin(page,'theme-browser-data');
  await post('/api/commercial/profile',{kind:'foreman',title:'Тестовая мастерская',contact:'public@example.test',description:'Только временные проверочные данные'});
  await post('/api/commercial/clients',{name:'Клиент сметы',contact:'private-client@example.test',notes:'PRIVATE_CLIENT_NOTE',active:true});
  let data=(await get('/api/commercial')).commercial;const clientId=data.clients[0].id;
  await post('/api/commercial/objects',{title:'Ремонт кухни',address:'Тестовый адрес',client_id:clientId,status:'active',budget_rub:100000,actual_rub:0});
  await page.evaluate(()=>hpointWorkspace.refresh());await page.goto(base+'/#/work');await page.locator('.commercialNavigation').waitFor();await workTab(page,'Сметы');
  assert.match(await page.locator('.estimateWorkspaceHero').innerText(),/Сметы без сложностей/);assert.equal(await page.locator('.estimateEmpty').isVisible(),true);checks+=2;
  await form().locator('[name=title]').fill('Смета ремонта кухни');await form().locator('[name=object_id]').selectOption({label:'Ремонт кухни'});await form().locator('[name=client_id]').selectOption(String(clientId));
  await form().locator('.estimateDocumentFields>summary').click();await form().locator('[name=number]').fill('КУХ-2026-01');await form().locator('[name=issued_on]').fill('2026-10-30');await form().locator('[name=valid_until]').fill('2026-11-30');await form().locator('[name=notes]').fill('Стоимость согласуется до начала работ.');
  let line=form().locator('[data-estimate-line]').first();await line.locator('[name=line_title]').fill('Краска и расходные материалы');await line.locator('[name=line_kind]').selectOption('material');await line.locator('[name=line_quantity]').fill('2,5');await line.locator('[name=line_unit]').fill('комплект');await line.locator('[name=line_price]').fill('100,20');await line.locator('.estimateLinePrivate>summary').click();await line.locator('[name=line_cost]').fill('50,10');
  await form().getByRole('button',{name:'+ Строка',exact:true}).click();line=form().locator('[data-estimate-line]').nth(1);await line.locator('[name=line_title]').fill('Подготовка и окраска');await line.locator('[name=line_unit]').fill('час');await line.locator('[name=line_quantity]').fill('3');await line.locator('[name=line_price]').fill('80');await line.locator('.estimateLinePrivate>summary').click();await line.locator('[name=line_cost]').fill('40');
  await form().locator('.estimateAdjustments>summary').click();await form().locator('[name=markup_percent]').fill('10');await form().locator('[name=discount_percent]').fill('5');await form().locator('.estimatePrivateSummary>summary').click();await page.getByText('Расчёт проверен.',{exact:true}).waitFor();
  assert.match(await form().locator('[data-estimate-subtotal]').innerText(),/490,50/);assert.match(await form().locator('[data-estimate-total]').innerText(),/512,57/);assert.match(await form().locator('[data-estimate-cost]').innerText(),/245,25/);assert.match(await form().locator('[data-estimate-profit]').innerText(),/267,32/);checks+=4;
  const liveForm=await form().evaluate(node=>(window.qaEstimateForm=node,true));await form().locator('[name=notes]').focus();await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await form().evaluate(node=>window.qaEstimateForm===node),true);assert.equal(await form().locator('[name=notes]').inputValue(),'Стоимость согласуется до начала работ.');checks+=2;
  for(const theme of ['light','dark'])for(const width of [320,390,768,1440]){await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:1000});await layout('Estimate editor '+width+' '+theme);if(width===390||width===1440){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,'work-estimate-editor-'+width+'-'+theme+'.png'),fullPage:true})}}
  await page.setViewportSize({width:1440,height:1000});await save();let row=saved('Смета ремонта кухни');await row.waitFor();assert.equal(await page.locator('.estimateEditor').evaluate(node=>node.open),false);checks++;
  data=(await get('/api/commercial')).commercial;let estimate=data.estimates[0];assert.equal(estimate.total_rub,'512.57');assert.equal(estimate.client_id,clientId);assert.equal(estimate.items[0].kind,'material');assert.equal(Number(estimate.discount_percent),5);checks+=4;
  await row.locator('.estimatePreview>summary').click();assert.match(await row.innerText(),/Краска и расходные материалы/);assert.match(await row.innerText(),/Подготовка и окраска/);assert.match(await row.innerText(),/КУХ-2026-01/);checks+=3;
  const clientPdf=await download(row,'Скачать PDF','pdf'),clientXlsx=await download(row,'Скачать Excel','xlsx');
  await row.locator('.estimateMore>summary').click();await download(row,'Внутренний PDF','pdf');const internalXlsx=await download(row,'Внутренний Excel','xlsx');
  const verifyXlsx=String.raw`import sys,zipfile,json,xml.etree.ElementTree as ET
for index,path in enumerate(sys.argv[1:]):
 with zipfile.ZipFile(path) as archive:
  body='\n'.join(''.join(ET.fromstring(archive.read(name)).itertext()) for name in archive.namelist() if name.endswith('.xml'))
  raw='\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist() if name.endswith('.xml'))
  assert 'Смета ремонта кухни' in body and 'Краска и расходные материалы' in body
  assert 'PRIVATE_CLIENT_NOTE' not in body and 'private-client@example.test' not in body
  if index==0:assert 'Себестоимость' not in body and 'Прибыль' not in body and 'прибыль' not in body
  else:assert 'Себестоимость' in body
  assert '<f>' in raw and 'workbook.xml' in archive.namelist()[archive.namelist().index('xl/workbook.xml')]
print(json.dumps({'xlsx_content':True,'private_fields_protected':True}))`;
  execFileSync(path.join(__dirname,'..','.venv','Scripts','python.exe'),['-c',verifyXlsx,clientXlsx,internalXlsx],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});checks+=5;
  await row.getByRole('button',{name:'Отметить согласованной',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-estimate-status="approved"]'));checks++;
  await page.locator('[name=estimate_query]').fill('несуществующая позиция');assert.equal(await row.isVisible(),false);assert.equal(await page.locator('[data-estimate-no-results]').isVisible(),true);await page.locator('[name=estimate_query]').fill('Краска');assert.equal(await row.isVisible(),true);checks+=3;
  await row.getByRole('button',{name:'Изменить',exact:true}).click();await form().locator('[name=title]').fill('Уточнённая смета кухни');await form().locator('[name=notes]').fill('Уточнённые сроки: после согласования.');await save('Сохранить смету');row=saved('Уточнённая смета кухни');await row.waitFor();checks++;
  await row.locator('.estimateMore>summary').click();await row.getByRole('button',{name:'Создать копию',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.estimateSavedList [data-estimate-id]').length===2);data=(await get('/api/commercial')).commercial;const copy=data.estimates.find(item=>item.id!==estimate.id);assert.equal(copy.status,'draft');assert.equal(copy.total_rub,'512.57');checks+=2;
  await page.locator('[name=estimate_query]').fill('');const copyRow=page.locator('[data-estimate-id="'+copy.id+'"]');await copyRow.locator('.estimateMore>summary').click();page.once('dialog',dialog=>dialog.accept());await copyRow.getByRole('button',{name:'Удалить',exact:true}).click();await copyRow.waitFor({state:'detached'});assert.equal((await get('/api/commercial')).commercial.estimates.length,1);checks++;
  for(const theme of ['light','dark'])for(const width of [320,390,768,1440]){await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:1000});await layout('Saved estimates '+width+' '+theme);if(width===390||width===1440){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,'work-estimate-saved-'+width+'-'+theme+'.png'),fullPage:true})}}
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);checks+=2;console.log(JSON.stringify({ok:true,checks,errors,estimateEditor:true,serverTotals:true,fullCrud:true,clientPdf:true,realExcel:true,privateFieldsProtected:true,responsiveThemes:true,downloads:downloads.map(file=>path.basename(file))}));
 }catch(error){console.error('Work estimate UI:',await page.locator('#commercialWorkspace').innerText().catch(()=>''));console.error(errors);await page.screenshot({path:path.join(output,'work-estimate-failure.png'),fullPage:true}).catch(()=>{});throw error}
 finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
