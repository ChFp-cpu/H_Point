/* The first mobile screen must offer both real Help actions before categories. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),errors=[];let checks=0;
 try{
  for(const identity of ['theme-browser-data','theme-browser-empty']){
   const context=await browser.newContext({viewport:{width:375,height:780},colorScheme:'light',reducedMotion:'reduce'});
   await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));await emailLogin(page,identity);
   if(identity==='theme-browser-data'){
    const response=await context.request.post(base+'/api/commercial/profile',{data:{kind:'trainer',title:'Тестовый рабочий кабинет',description:'Только локальная проверка',contact:''}});
    assert.equal(response.status(),200);checks++;await page.evaluate(()=>hpointWorkspace.refresh());
   }
   for(const width of [320,360,375,390,414,768,1440])for(const colorScheme of ['light','dark']){
    await page.setViewportSize({width,height:width<=414?780:1000});await page.emulateMedia({colorScheme});
    await page.evaluate(()=>{go('home');scrollTo(0,0)});await page.locator('.hpHomeHero').waitFor();
    const hero=page.locator('.hpHomeHero'),need=hero.getByRole('button',{name:'Нужна помощь',exact:false}),offer=hero.getByRole('button',{name:'Хочу помочь',exact:true});
    assert.equal(await need.isVisible(),true);assert.equal(await offer.isVisible(),true);checks+=2;
    const layout=await page.evaluate(()=>{
     const rect=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom,right:r.right}};
     const shell=document.getElementById('hpointWorkspace'),primary=[...shell.children].filter(node=>node.classList.contains('workspaceNotices')===false&&node.getBoundingClientRect().height>0);
     return {firstIsHero:primary[0]?.classList.contains('hpHomeHero'),hero:rect(document.querySelector('.hpHomeHero')),categories:rect(document.querySelector('#hpointWorkspace>.hpCategorySection')),need:rect(document.querySelector('.hpHomeHero [data-ws-action=request]')),offer:rect(document.querySelector('.hpHomeHero [data-ws-action=help-tab]')),nav:rect(document.querySelector('.nav')),height:innerHeight,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1};
    });
    assert.equal(layout.firstIsHero,true,'Primary actions must be the first home section');
    assert.ok(layout.hero.y<layout.categories.y,'Categories follow the primary actions');
    assert.equal(layout.overflow,false,'No horizontal overflow');checks+=3;
    for(const button of [layout.need,layout.offer]){assert.ok(button.y>=layout.nav.bottom-1);assert.ok(button.bottom<layout.height-70,'Both actions fit the first screen above the bottom menu');assert.ok(button.x>=0&&button.right<=layout.width);assert.ok(button.h>=44);checks+=4}
    await need.click();await page.locator('#qw').waitFor({state:'visible'});await page.locator('#qw').fill('Локальная проверка главной');assert.equal(await page.locator('#qw').inputValue(),'Локальная проверка главной');checks++;await page.evaluate(()=>closeModal());
    await offer.click();await page.locator('.hpHelpHero').waitFor();assert.equal(await page.evaluate(()=>hpointWorkspace.state.route),'help');assert.equal(await page.evaluate(()=>hpointWorkspace.state.helpTab),'open');assert.equal(await page.locator('.helpNavigation [data-tab=open]').getAttribute('aria-current'),'page');checks+=3;
    await page.evaluate(()=>{go('home');scrollTo(0,0)});await hero.waitFor();
    if(identity==='theme-browser-data'&&[320,375,1440].includes(width))await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'mobile-home-actions-'+width+'-'+colorScheme+'.png'),fullPage:true});
   }
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,firstScreenActions:true,realRequestWizard:true,realHelpNavigation:true,emptyAndExistingAccounts:true}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
