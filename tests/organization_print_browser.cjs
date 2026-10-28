const {workTab}=require('./work_browser_navigation.cjs');
/* The native print action exposes one client estimate, with no dark-theme ink or private costs. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1500}}),page=await context.newPage(),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());page.on('pageerror',error=>errors.push(error.message));
 const post=async(url,data)=>{const response=await context.request.post(base+url,{data});assert.equal(response.status(),200,await response.text());return response.json()};
 try{
  await emailLogin(page,'theme-browser-data');await post('/api/commercial/profile',{kind:'organization',title:'Печатная тестовая организация',contact:'public@example.test'});
  const first=(await post('/api/commercial/estimates',{title:'Смета для клиента',markup_percent:'10',items:[{title:'Услуга для клиента',unit:'шт.',quantity:'3',price_rub:'100',cost_rub:'40'}]})).result.id;
  await post('/api/commercial/estimates',{title:'Другая закрытая смета',items:[{title:'Посторонняя работа',unit:'шт.',quantity:'1',price_rub:'999',cost_rub:'99'}]});
  await page.evaluate(()=>hpointWorkspace.refresh());await page.evaluate(()=>hpointCommercial.open('estimates'));await page.locator('[data-estimate-id="'+first+'"]').waitFor();
  await page.evaluate(()=>{window.print=()=>{const visible=el=>Boolean(el?.getClientRects().length)&&getComputedStyle(el).visibility!=='hidden'&&getComputedStyle(el).display!=='none',selected=document.querySelector('.commercialEstimateSelected');window.qaPrint={selected:selected?.dataset.estimateId,texts:[...document.querySelectorAll('.commercialEstimatePrint b,.commercialEstimatePrint td,.commercialEstimatePrint th,.commercialEstimatePrint small,.commercialPrint h2,.commercialPrint p')].filter(visible).map(el=>el.textContent),colors:[...selected.querySelectorAll('b,td,th,small,p,h2')].filter(visible).map(el=>getComputedStyle(el).color),internal:[...document.querySelectorAll('.commercialEstimateInternal')].some(visible),buttons:[...selected.querySelectorAll('button')].some(visible),other:[...document.querySelectorAll('.commercialEstimatePrint')].filter(el=>el!==selected).some(visible),nav:visible(document.querySelector('.nav')),form:visible(document.querySelector('[data-commercial-form=estimates]')),height:document.body.scrollHeight,selectedHeight:selected.getBoundingClientRect().height,selectedTop:selected.getBoundingClientRect().top,roots:[...document.querySelectorAll('[data-hpoint-print-root]')].map(el=>({name:el.id||el.className,height:el.getBoundingClientRect().height,top:el.getBoundingClientRect().top,before:getComputedStyle(el,'::before').content,after:getComputedStyle(el,'::after').content})),background:getComputedStyle(document.body).backgroundColor}}});
  for(const colorScheme of ['light','dark']){
   await page.emulateMedia({media:'print',colorScheme});await page.locator('[data-estimate-id="'+first+'"]').getByRole('button',{name:'Печать / PDF',exact:true}).click();const capture=await page.evaluate(()=>window.qaPrint);
   assert.equal(capture.selected,String(first));assert.equal(capture.internal,false);assert.equal(capture.buttons,false);assert.equal(capture.other,false);assert.equal(capture.nav,false);assert.equal(capture.form,false);assert.equal(capture.background,'rgb(255, 255, 255)');assert.ok(capture.colors.every(color=>color==='rgb(23, 37, 31)'));assert.match(capture.texts.join(' '),/Смета для клиента/);assert.match(capture.texts.join(' '),/Печатная тестовая организация/);assert.doesNotMatch(capture.texts.join(' '),/Себестоимость|прибыль|Посторонняя|Другая закрытая/);assert.ok(capture.height<=capture.selectedHeight+3,JSON.stringify(capture));assert.equal(await page.locator('.hpWorkPrinting,[data-hpoint-print-root],.commercialEstimateSelected').count(),0);checks+=13;
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,selectedEstimateOnly:true,privateCostsHidden:true,lightDarkPrintInk:true,noHiddenFormPrintSpace:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
