/* Responsive header containment with real local login and synthetic balances. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Disposable local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:375,height:844},reducedMotion:'reduce'}),errors=[];let checks=0;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 let pro=true,amount=10000;
 await page.route(base+'/api/sync',async route=>{const response=await route.fetch(),data=await response.json();data.user={...data.user,pro_active:pro,pro_until:'2099-01-01T00:00:00+00:00',balance:amount,stats:{...data.user.stats,helped_avg:5,helped_reviews:10}};data.wallet={...data.wallet,balance_rub:amount,test_balance_rub:amount};await route.fulfill({response,json:data})});
 const geometry=()=>page.evaluate(()=>{
  const box=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
  const button=document.querySelector('.workspaceHeaderActions [data-route=profile]'),label=button.querySelector('[data-header-profile-label]'),badge=button.querySelector('[data-header-pro]'),wallet=button.querySelector('[data-header-mobile-wallet]');
  const range=document.createRange();range.setStart(label.firstChild,0);range.setEnd(label.firstChild,7);const word=range.getBoundingClientRect();
  return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,nav:box(document.querySelector('.nav')),brand:box(document.querySelector('.brandLogo')),actions:box(document.querySelector('.workspaceHeaderActions')),support:box(document.querySelector('.workspaceSupport')),request:box(document.querySelector('.workspaceHeaderActions [data-ws-action=request]')),profile:box(button),label:box(label),badge:badge.hidden?null:box(badge),wallet:box(wallet),word:{x:word.x,right:word.right,y:word.y,bottom:word.bottom},style:{profileJustify:getComputedStyle(button).justifyItems,labelJustify:getComputedStyle(label).justifySelf,labelWidth:getComputedStyle(label).width,walletWidth:getComputedStyle(wallet).width},walletText:wallet.textContent,walletClientWidth:wallet.clientWidth,walletScrollWidth:wallet.scrollWidth};
 });
 const inside=(a,b)=>a.x>=b.x-.5&&a.right<=b.right+.5&&a.y>=b.y-.5&&a.bottom<=b.bottom+.5;
 const separate=(a,b)=>a.right<=b.x+.5||b.right<=a.x+.5||a.bottom<=b.y+.5||b.bottom<=a.y+.5;
 try{
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointWorkspace.refresh());
  for(const width of [320,360,375,390,414,768,900])for(const colorScheme of ['light','dark'])for(const activePro of [true,false]){
   pro=activePro;amount=activePro?10000:999999999;await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme});await page.evaluate(()=>hpointWorkspace.refresh());
   let shape;for(const route of ['home','wallet','billing']){
    await page.evaluate(route=>go(route),route);await page.locator('.workspaceHeaderActions').waitFor();
    const g=await geometry();if(process.env.HPOINT_HEADER_DIAGNOSTIC==='1')console.log(JSON.stringify({width,colorScheme,pro,route,...g}));
    assert.ok(g.scrollWidth<=width+1,'No horizontal page overflow');assert.ok(inside(g.profile,g.actions),'Profile stays in toolbar');assert.ok(inside(g.label,g.profile),'Profile label stays in its button');assert.ok(inside(g.wallet,g.profile),'Wallet stays in profile button');assert.ok(inside(g.word,g.label),'The complete word Профиль remains visible');checks+=5;
    if(amount===10000){assert.ok(g.walletScrollWidth<=g.walletClientWidth+1,'Ordinary HP and RUB amounts remain fully readable');checks++}
    if(shape){for(const key of ['nav','brand','actions','profile','support','request'])for(const prop of ['x','y','w','h'])assert.ok(Math.abs(g[key][prop]-shape[key][prop])<=.5,'Routing must not move header '+key+'.'+prop);checks++}else shape=g;
    if(g.badge){assert.ok(inside(g.badge,g.profile));assert.ok(separate(g.label,g.badge),'Profile and PRO must not overlap');checks+=2}
    assert.ok(separate(g.label,g.wallet),'Profile and balance must not overlap');assert.ok(separate(g.support,g.profile));assert.ok(separate(g.profile,g.request));assert.ok(separate(g.brand,g.actions),'Brand and toolbar do not overlap');assert.ok(g.support.w>=44&&g.support.h>=44);assert.ok(g.request.w>=44&&g.request.h>=44);checks+=6;
    if(route==='home'&&activePro&&[320,375,900].includes(width))await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'mobile-header-'+width+'-'+colorScheme+'.png'),fullPage:false});
   }
  }
  assert.deepEqual(errors,[]);checks++;console.log(JSON.stringify({ok:true,checks,errors,profileContained:true,proAndWalletContained:true,allMobileWidths:true}));
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
