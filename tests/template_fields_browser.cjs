/* Complete template round-trip, using a disposable account and no real funds. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:375,height:950}}),errors=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const get=async path=>(await context.request.get(base+path)).json();
 async function post(path,data){const r=await context.request.post(base+path,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 try{
  await emailLogin(page,'theme-browser-empty');await post('/api/payments/hp',{item_type:'pro',purchase_key:'template-fields-pro'});
  const fields={what:'Полный перенос условий шаблона',place:'Тестовый район',time_needed:'В четверг после 17:30',urgency:'Особый срок',details:'Нужны инструменты.\nВторая строка подробностей.',category:'tools',expires_in_hours:73,reward_rub:1234,lat:55.75,lon:37.62};
  const quote=(await get('/api/requests/quote?reward_rub=1234')).quote;
  const original=await post('/api/requests',{...fields,pricing_version:quote.version,expected_total_rub:quote.total_rub});
  const saved=await post('/api/personal/templates',{name:'Сохранено из заявки',request_id:original.request_id});
  for(const key of Object.keys(fields)){assert.equal(saved.template.fields[key],fields[key],key+' stored from existing request');checks++}
  await page.evaluate(()=>hpointWorkspace.refresh());await page.evaluate(()=>{hpointWorkspace.state.helpTab='mine';go('help')});
  await page.locator('.personalTools>summary').click();await page.locator('.personalTools [data-personal-action="templates"]').click();await page.locator('[data-personal-action="use-template"]').click();
  await page.locator('#qd').waitFor({state:'visible'});assert.equal(await page.evaluate(()=>hpointRequestStep),2);checks++;
  const ids={what:'qw',place:'qp',time_needed:'qt',urgency:'qu',details:'qd',category:'qc',expires_in_hours:'requestHours',reward_rub:'rewardRub'};
  for(const [key,id]of Object.entries(ids)){assert.equal(await page.locator('#'+id).inputValue(),String(fields[key]),key+' restored into form');checks++}
  await page.waitForFunction(()=>hpointPersonal.currentQuote()?.total_rub===1419);
  assert.match(await page.locator('#requestDuration').innerText(),/73/);assert.match(await page.locator('#rewardValue').innerText(),/1\s*234/);assert.match(await page.locator('#personalRequestQuote').innerText(),/1\s*419/);checks+=3;
  assert.equal(await page.locator('#rewardRub').isVisible(),true);assert.equal(await page.locator('#requestScheduledAt').inputValue(),'');checks+=2;
  // Saving and applying a second set of draft conditions must preserve them too.
  await page.locator('#qd').fill('Новые подробности\nс двумя строками');await page.locator('#rewardRub').fill('2468');await page.locator('#requestHours').fill('12');
  await page.locator('#personalWizardTemplates>summary').click();await page.locator('#personalDraftName').fill('Сохранено из формы');await page.locator('[data-personal-action="save-draft"]').click();await page.locator('#rqerr').getByText(/Шаблон сохранён/).waitFor();
  const templates=(await get('/api/personal')).templates,second=templates.find(x=>x.name==='Сохранено из формы');assert.equal(second.fields.details,'Новые подробности\nс двумя строками');assert.equal(second.fields.reward_rub,2468);assert.equal(second.fields.expires_in_hours,12);checks+=3;
  await page.locator('#personalWizardTemplates>summary').click();await page.locator('#personalWizardTemplates>summary').click();await page.locator('#personalWizardTemplateSelect').selectOption(String(second.id));await page.locator('[data-personal-action="fill-draft"]').click();
  await page.waitForFunction(()=>hpointPersonal.currentQuote()?.total_rub===2838);
  const response=page.waitForResponse(r=>r.url()===base+'/api/requests'&&r.request().method()==='POST');await page.locator('#createRequestButton').click();assert.equal((await response).status(),200);checks++;
  const rows=(await get('/api/sync')).requests,newest=rows.filter(r=>r.id!==original.request_id).sort((a,b)=>b.id-a.id)[0];
  assert.equal(newest.details,second.fields.details);assert.equal(newest.reward_rub,2468);assert.equal(newest.time_needed,fields.time_needed);assert.equal(newest.urgency,fields.urgency);assert.equal(Math.round((Date.parse(newest.expires_at)-Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(newest.created_at)?newest.created_at:newest.created_at.replace(' ','T')+'Z'))/3600000),12);checks+=5;
  assert.equal((await get('/api/wallet')).wallet.test_balance_rub,0);assert.equal(newest.reward_payment_status,'none');checks+=2;
  for(const colorScheme of ['light','dark'])for(const width of [320,375,768,1440]){await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:950});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);checks++}
  assert.deepEqual(errors,[]);checks++;console.log(JSON.stringify({ok:true,checks,errors,allTemplateFields:true,arbitraryWholeRubles:true,durationFromExistingRequest:true,actualPublishedFields:true}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
