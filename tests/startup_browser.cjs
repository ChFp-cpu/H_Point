/* Public startup remains usable when map providers are unreachable. */
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844}}),external=[],errors=[];let checks=0;
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();external.push(route.request().url());return route.abort()});
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 try{
  const start=Date.now();await page.goto(base,{waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'Войти',exact:true}).first().waitFor();
  assert.ok(Date.now()-start<5000,'Blocked map provider must not delay the landing');checks++;
  assert.equal(await page.locator('link[href*="fonts.googleapis"]').count(),0);checks++;
  assert.equal(await page.locator('script[src*="api-maps"]').count(),0);checks++;
  await page.evaluate(()=>document.fonts.ready);assert.equal(await page.evaluate(()=>document.fonts.check('500 14px Manrope')),true);checks++;
  assert.deepEqual(external,[]);checks++;
  assert.equal(await page.locator('link[rel=canonical]').count(),1);checks++;
  assert.match(await page.locator('meta[name=description]').getAttribute('content'),/email/);checks++;
  for(const path of ['/robots.txt','/sitemap.xml','/favicon.ico','/assets/favicon-192.png','/assets/manrope-variable.ttf','/assets/hpoint-logo.webp','/assets/hpoint-logo-dark.webp']){const response=await context.request.get(base+path);assert.equal(response.status(),200,path);checks++}
  for(const method of ['get','head']){const response=await context.request[method](base+'/games');assert.equal(response.status(),410);assert.match(response.headers()['x-robots-tag'],/noindex/);checks+=2}
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointWorkspace.refresh());
  assert.deepEqual(await page.locator('#sitePrimaryNav button').allTextContents(),['Главная','Помощь','Активности']);checks++;
  await page.goto(base+'/#/help');await page.locator('.helpNavigation').waitFor();
  assert.deepEqual(external,[]);checks++;
  await page.locator('#helpMore summary').click();await page.locator('[data-ws-action=help-tab][data-tab=map]').click();
  await page.getByRole('button',{name:'Повторить',exact:true}).waitFor();
  assert.ok(external.some(url=>url.includes('api-maps.yandex.ru')));checks++;
  assert.equal(await page.locator('#sitePrimaryNav [data-route=home]').isEnabled(),true);checks++;
  await page.locator('#sitePrimaryNav [data-route=home]').click();await page.locator('.homeTasks').waitFor();
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({ok:true,checks,errors,lazyMap:true,localFonts:true,noExternalStartupRequests:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
