/* Support remains reachable through the real responsive header and account menu. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),errors=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 const button=()=>page.locator('.workspaceHeaderActions [data-ws-action="support"]');
 async function open(){await button().click();await page.getByRole('heading',{name:'Поддержка',exact:true}).waitFor();assert.equal(await page.locator('#supportSubject').isVisible(),true);assert.equal(await page.locator('#supportMessage').isVisible(),true);await page.evaluate(()=>closeModal());checks+=2}
 async function audit(label){
  assert.equal(await button().isVisible(),true,label);assert.equal(await button().getAttribute('aria-label'),'Поддержка');checks+=2;
  const geometry=await button().evaluate(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,viewport:innerWidth}});
  assert.ok(geometry.w>=44&&geometry.h>=44,label+' touch target');assert.ok(geometry.x>=0&&geometry.right<=geometry.viewport,label+' support within viewport');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,label+' no overflow');checks+=3;
 }
 try{
  await emailLogin(page,'mobile-helper');
  for(const width of [320,390,700,768,1024,1440])for(const colorScheme of ['light','dark']){
   await page.setViewportSize({width,height:width<768?844:1000});await page.emulateMedia({colorScheme});await page.evaluate(()=>hpointWorkspace.refresh());
   await audit(width+' '+colorScheme);await open();
  }
  // PRO and a Work menu item must not squeeze the support control off a phone.
  await page.route(base+'/api/sync',async route=>{const response=await route.fetch(),data=await response.json();data.user={...data.user,stats:{...data.user.stats,helped_avg:5},pro_active:true,pro_until:'2099-01-01T00:00:00+00:00'};await route.fulfill({response,json:data})});
  const created=await context.request.post(base+'/api/commercial/profile',{data:{kind:'organization',title:'Тест поддержки',description:'Синтетическая организация',contact:''}});assert.equal(created.status(),200);checks++;
  for(const width of [320,360,375,390,420,430,768,900,1024,1440]){
   await page.setViewportSize({width,height:844});await page.evaluate(()=>hpointWorkspace.refresh());await audit(width+' with rating, PRO and work');
   assert.equal(await page.locator('.workspaceHeaderActions .workspaceProBadge').isVisible(),true);assert.equal(await page.locator('#sitePrimaryNav [data-route="work"]').isVisible(),true);checks+=2;
  }
  await page.setViewportSize({width:390,height:844});
  for(const route of ['home','help','activities','league','work','profile','profile/wallet','profile/billing']){
   await page.goto(base+'/#/'+route);await page.locator('#hpointWorkspace').waitFor();await page.evaluate(()=>hpointWorkspace.refresh());await open();
  }
  await page.goto(base+'/#/profile');await page.evaluate(()=>hpointWorkspace.refresh());
  const fallback=page.locator('.workspaceAccountNav [data-ws-action="support"]');if(!await fallback.isVisible())await page.locator('#accountMore summary').click();assert.equal(await fallback.isVisible(),true);await fallback.click();await page.locator('#supportSubject').waitFor();checks++;
  await page.locator('#supportSubject').fill('Проверка мобильной поддержки');await page.locator('#supportMessage').fill('Синтетическое обращение в локальной тестовой базе.');
  const sent=page.waitForResponse(response=>response.url()===base+'/api/support'&&response.request().method()==='POST');await page.locator('#modalbody').getByRole('button',{name:'Отправить',exact:true}).click();assert.equal((await sent).status(),200);
  await page.locator('#supportTickets').getByText('Проверка мобильной поддержки',{exact:true}).waitFor();checks++;
  await page.evaluate(()=>closeModal());const before=await page.locator('.nav').evaluate(node=>node.getBoundingClientRect().height);await page.evaluate(()=>{window.qaSupportButton=document.querySelector('.workspaceHeaderActions [data-ws-action="support"]')});await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await button().evaluate(node=>node===window.qaSupportButton),true);assert.equal(await page.locator('.nav').evaluate(node=>node.getBoundingClientRect().height),before);checks+=2;
  await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'mobile-support-light.png'),fullPage:true});await page.emulateMedia({colorScheme:'dark'});await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'mobile-support-dark.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,supportVisible:true,localTicketStored:true,profileFallback:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
