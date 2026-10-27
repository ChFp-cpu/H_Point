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
  for(const colorScheme of ['light','dark'])for(const width of [320,390,1440]){
   await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:844});
   assert.deepEqual(await page.locator('.welcomeDirections b').allTextContents(),['Помощь','Для работы']);checks++;
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checks++;
   await page.evaluate(()=>authForm(true));await page.locator('.authDirections').waitFor();
   assert.deepEqual(await page.locator('.authDirections b').allTextContents(),['Помощь','Для работы']);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checks+=2;
   await page.evaluate(()=>closeModal());
  }
  const gestures=await page.evaluate(()=>{
   const wheel=new WheelEvent('wheel',{ctrlKey:true,deltaY:-120,bubbles:true,cancelable:true});document.dispatchEvent(wheel);
   const normal=new WheelEvent('wheel',{deltaY:120,bubbles:true,cancelable:true});document.dispatchEvent(normal);
   const pinch=new Event('gesturestart',{bubbles:true,cancelable:true});document.dispatchEvent(pinch);
   return{pinchWheel:wheel.defaultPrevented,normalWheel:normal.defaultPrevented,pinch:pinch.defaultPrevented,touchAction:getComputedStyle(document.documentElement).touchAction,viewport:document.querySelector('meta[name=viewport]').content};
  });
  assert.equal(gestures.pinchWheel,true);assert.equal(gestures.normalWheel,false);assert.equal(gestures.pinch,true);assert.equal(gestures.touchAction,'pan-x pan-y');assert.match(gestures.viewport,/maximum-scale=1/);assert.match(gestures.viewport,/user-scalable=no/);checks+=6;
  const desktopSize=await page.evaluate(()=>({width:innerWidth,ratio:devicePixelRatio}));
  await page.keyboard.press('Control+Equal');await page.keyboard.press('Control+Minus');await page.keyboard.down('Control');await page.mouse.wheel(0,-180);await page.keyboard.up('Control');await page.waitForTimeout(100);
  assert.deepEqual(await page.evaluate(()=>({width:innerWidth,ratio:devicePixelRatio})),desktopSize);checks++;
  const keys=await page.evaluate(()=>['+','-','='].map(key=>{const event=new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true,cancelable:true});document.dispatchEvent(event);return event.defaultPrevented}));assert.deepEqual(keys,[true,true,true]);checks++;
  await page.setViewportSize({width:390,height:844});
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointWorkspace.refresh());
  assert.deepEqual(await page.locator('#sitePrimaryNav button').allTextContents(),['Главная','Помощь','Активности']);checks++;
  await page.goto(base+'/#/help');await page.locator('.helpNavigation').waitFor();
  assert.deepEqual(external,[]);checks++;
  await page.locator('#helpMore summary').click();await page.locator('[data-ws-action=help-tab][data-tab=map]').click();
  await page.getByRole('button',{name:'Повторить',exact:true}).waitFor();
  assert.ok(external.some(url=>url.includes('api-maps.yandex.ru')));checks++;
  assert.equal(await page.locator('#sitePrimaryNav [data-route=home]').isEnabled(),true);checks++;
  await page.locator('#sitePrimaryNav [data-route=home]').click();await page.locator('.homeTasks').waitFor();
  const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  try{
   await mobile.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
   const touch=await mobile.newPage();touch.on('pageerror',error=>errors.push(error.message));await touch.goto(base);await touch.getByRole('button',{name:'Войти',exact:true}).first().waitFor();
   const cdp=await mobile.newCDPSession(touch),scale=await touch.evaluate(()=>visualViewport.scale);
   await cdp.send('Input.synthesizePinchGesture',{x:195,y:300,scaleFactor:1.6,relativeSpeed:800,gestureSourceType:'touch'});await touch.waitForTimeout(200);
   assert.ok(Math.abs((await touch.evaluate(()=>visualViewport.scale))-scale)<0.01,'A native touch pinch must not zoom the page');checks++;
   await cdp.send('Input.synthesizeScrollGesture',{x:195,y:600,yDistance:-220,gestureSourceType:'touch'});await touch.waitForTimeout(150);
   if(!(await touch.evaluate(()=>scrollY>0))){await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:195,y:600}]});for(let y=570;y>=300;y-=30){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:195,y}]});await touch.waitForTimeout(20)}await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await touch.waitForTimeout(200)}
   assert.ok(await touch.evaluate(()=>scrollY>0),'Touch scrolling remains available');checks++;
  }finally{await mobile.close()}
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({ok:true,checks,errors,lazyMap:true,localFonts:true,noExternalStartupRequests:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
