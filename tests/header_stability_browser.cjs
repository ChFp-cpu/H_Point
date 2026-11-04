/* Header ownership and cold-load frames; disposable local email accounts only. */
'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[];let checks=0,closing=false,releaseBilling,releaseAsset;
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 await context.addInitScript(()=>{
  const visible=node=>{if(!node)return false;const rect=node.getBoundingClientRect(),style=getComputedStyle(node);return rect.width>0&&rect.height>0&&style.display!=='none'&&style.visibility!=='hidden'&&style.opacity!=='0'};
  window.qaHeaderFrames={oldHeader:[],legacyPanels:[],earlyLanding:[],heights:[],oldHeaderWrites:0};
  new MutationObserver(records=>{if(!window.hpointWorkspace?.state?.installed)return;for(const record of records)for(const node of record.addedNodes){if(node.nodeType===1&&(node.id==='globalBalance'||node.querySelector?.('#globalBalance')))window.qaHeaderFrames.oldHeaderWrites++}}).observe(document,{childList:true,subtree:true});
  function sample(){
   const t=Math.round(performance.now()),nav=document.querySelector('.nav'),app=document.getElementById('app'),landing=document.getElementById('landing');
   if(visible(document.getElementById('globalBalance')))window.qaHeaderFrames.oldHeader.push(t);
   const legacy=[...document.querySelectorAll('#app>.appHead,#app>.tabs,#app>.panel.active')].filter(visible);
   if(visible(app)&&legacy.length)window.qaHeaderFrames.legacyPanels.push({t,ids:legacy.map(node=>node.id||node.className)});
   if(visible(landing)&&!landing.querySelector('.peopleCover'))window.qaHeaderFrames.earlyLanding.push(t);
   if(window.hpointWorkspace?.state?.installed&&visible(nav)&&document.querySelector('.workspaceHeaderActions'))window.qaHeaderFrames.heights.push(Math.round(nav.getBoundingClientRect().height*10)/10);
   requestAnimationFrame(sample);
  }requestAnimationFrame(sample);
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 async function refresh(){await page.evaluate(()=>hpointWorkspace.refresh())}
 async function header(){return page.evaluate(()=>{const box=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};return {nav:box(document.querySelector('.nav')),primary:box(document.getElementById('sitePrimaryNav')),actions:box(document.querySelector('.workspaceHeaderActions')),balance:box(document.querySelector('.workspaceBalance')),profile:document.querySelector('.workspaceHeaderActions [data-route=profile]')?.textContent,legacy:document.querySelectorAll('#globalBalance').length,navItems:[...document.querySelectorAll('#sitePrimaryNav [data-route]')].map(node=>node.dataset.route)}})}
 function sameShape(current,expected,message){for(const key of ['nav','primary','actions','balance'])for(const property of ['x','y','w','h'])assert.ok(Math.abs(current[key][property]-expected[key][property])<=1,message+' '+key+'.'+property+' expected '+expected[key][property]+' got '+current[key][property]);assert.equal(current.legacy,0);assert.deepEqual(current.navItems,expected.navItems);checks+=3}
 async function geometry(label){
  const issues=await page.evaluate(()=>{
   const visible=node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'},rect=node=>{const r=node.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}},name=node=>node.getAttribute('aria-label')||node.innerText||node.alt;
   const primary=document.querySelector('#sitePrimaryNav'),primaryRect=rect(primary),navRect=rect(document.querySelector('.nav')),issues=[],nodes=[...document.querySelectorAll('.brandLogo img,#sitePrimaryNav>button,#sitePrimaryNav>a,.workspaceHeaderActions>button')].filter(visible);
   if(document.documentElement.scrollWidth>innerWidth+1)issues.push({type:'document overflow',width:document.documentElement.scrollWidth});
   for(const node of nodes){const b=rect(node),label=name(node),isPrimary=node.parentElement===primary;
    if(b.left<-.5||b.right>innerWidth+.5)issues.push({type:'control outside viewport',label,b});
    if(node.tagName!=='IMG'&&(b.height<40||b.width<40))issues.push({type:'small control',label,b});
    const owner=isPrimary?primaryRect:navRect;if(b.left<owner.left-.5||b.right>owner.right+.5||b.top<owner.top-.5||b.bottom>owner.bottom+.5)issues.push({type:'control outside slot',label,b,owner});
    if(node.tagName==='IMG')continue;
    const walk=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);let text;while(text=walk.nextNode()){
     if(!text.textContent.trim()||!visible(text.parentElement)||parseFloat(getComputedStyle(text.parentElement).fontSize)===0)continue;
     const range=document.createRange();range.selectNodeContents(text);for(const r of range.getClientRects())if(r.width>.1&&(r.left<b.left+.5||r.right>b.right-.5||r.top<b.top-.5||r.bottom>b.bottom+.5))issues.push({type:'text outside button',label,text:text.textContent,font:getComputedStyle(text.parentElement).fontSize,b,textRect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom}});
    }
    const hit=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);if(hit&&!node.contains(hit))issues.push({type:'control covered',label,coveredBy:hit.tagName+'.'+hit.className});
   }
   for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=rect(nodes[i]),b=rect(nodes[j]);if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>.5&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>.5)issues.push({type:'overlap',a:name(nodes[i]),b:name(nodes[j]),aRect:a,bRect:b})}
   return issues;
  });
  assert.deepEqual(issues,[],label+' has distinct, readable header controls');checks++;
 }
 try{
  await emailLogin(page,'theme-browser-data');await refresh();
  const created=await context.request.post(base+'/api/commercial/profile',{data:{kind:'organization',title:'Тестовая организация интерфейса',description:'Только тестовая база',contact:''}});assert.equal(created.status(),200);checks++;
  await refresh();await page.evaluate(()=>go('wallet'));await page.locator('.workspaceWalletGrid').waitFor();await refresh();
  const baseline=await header();assert.deepEqual(baseline.navItems,['home','help','work','activities','admin']);assert.match(baseline.profile,/Профиль.*5\.0/);assert.equal(baseline.legacy,0);checks+=3;
  // A genuine delayed billing response used to replace the shared header with
  // the obsolete balance widget and force a second row.
  let observed;const held=new Promise(r=>releaseBilling=r),seen=new Promise(r=>observed=r);
  const billingHandler=async route=>{observed();await held;try{await route.continue()}catch(error){if(!closing)throw error}};await page.route(base+'/api/billing',billingHandler);
  await page.locator('.workspaceAccountNav [data-route=billing]').click();await seen;await page.waitForTimeout(100);sameShape(await header(),baseline,'Billing loading header');
  releaseBilling();await page.locator('.workspaceBillingGrid').waitFor();await refresh();sameShape(await header(),baseline,'Billing ready header');
  // Exercise inherited callers too: purchase callbacks and reload paths used
  // to invoke this function independently of the account navigation.
  await page.evaluate(()=>window.billing());sameShape(await header(),baseline,'Explicit billing refresh header');
  await page.evaluate(()=>{window.qaBalanceElement=document.querySelector('.workspaceBalance');window.qaPrimaryElement=document.querySelector('#sitePrimaryNav')});await refresh();await page.waitForTimeout(1200);
  assert.equal(await page.evaluate(()=>window.qaBalanceElement===document.querySelector('.workspaceBalance')),true);assert.equal(await page.evaluate(()=>window.qaPrimaryElement===document.querySelector('#sitePrimaryNav')),true);checks+=2;
  const syncHandler=async route=>{const response=await route.fetch(),data=await response.json();data.wallet={...data.wallet,balance_rub:37,test_balance_rub:37};await route.fulfill({response,json:data})};await page.route(base+'/api/sync',syncHandler);await refresh();
  assert.match(await page.locator('.workspaceBalance').innerText(),/37\s*₽/);sameShape(await header(),baseline,'Changed wallet header');checks++;
  await page.unroute(base+'/api/sync',syncHandler);await refresh();
  // An administrator who owns an organization has the longest primary menu.
  // PRO adds a badge to the other side of the header. Check both roles and
  // organization states; scrollWidth alone misses controls drawn on each other.
  let scenario={admin:true,work:true};
  const headerSync=async route=>{const response=await route.fetch(),data=await response.json();data.user={...data.user,role:scenario.admin?'admin':'user',pro_active:true,pro_until:'2099-01-01T00:00:00+00:00'};await route.fulfill({response,json:data})};
  const headerWork=async route=>{const response=await route.fetch(),data=await response.json();data.summary={...data.summary,exists:scenario.work};await route.fulfill({response,json:data})};
  await page.route(base+'/api/sync',headerSync);await page.route(base+'/api/billing',headerSync);await page.route(base+'/api/commercial/summary',headerWork);
  const widths=[320,360,375,390,420,700,701,768,900,901,1024,1100,1101,1120,1121,1200,1279,1280,1366,1439,1440,1600,1920];
  for(const admin of [true,false])for(const work of [true,false]){
   scenario={admin,work};await refresh();
   for(const colorScheme of ['light','dark'])for(const width of widths){
    const label=[admin?'admin':'member',work?'organization':'no organization',colorScheme,width].join(' ');
    await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:width<701?844:1000});await page.evaluate(()=>go('home'));await page.locator('.homeHero').waitFor();await geometry(label+' home');const homeHeader=await header();
    assert.deepEqual(homeHeader.navItems,['home','help',...(work?['work']:[]),'activities',...(admin?['admin']:[])]);checks++;
    if(admin){assert.equal(await page.locator('#sitePrimaryNav [data-route=admin]').getAttribute('aria-label'),'Панель администратора');assert.equal(await page.locator('#sitePrimaryNav [data-route=admin]').innerText(),width>=1440?'Панель администратора':'Админ');checks+=2}
    await page.evaluate(()=>go('billing'));await page.locator('.workspaceBillingGrid').waitFor();await geometry(label+' billing');sameShape(await header(),homeHeader,label+' same home/billing header');
    if(admin&&work&&[320,1121,1280,1440,1920].includes(width))await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'header-'+width+'-'+colorScheme+'.png'),fullPage:true});
   }
  }
  await page.unroute(base+'/api/sync',headerSync);await page.unroute(base+'/api/billing',headerSync);await page.unroute(base+'/api/commercial/summary',headerWork);await refresh();
  const frames=await page.evaluate(()=>window.qaHeaderFrames);assert.deepEqual(frames.oldHeader,[]);assert.deepEqual(frames.legacyPanels,[]);assert.equal(frames.oldHeaderWrites,0);checks+=3;
  // Delaying the first feature module leaves only the neutral boot state. The
  // obsolete app and undecorated landing page must never become visible.
  let assetObserved;const assetHeld=new Promise(r=>releaseAsset=r),assetSeen=new Promise(r=>assetObserved=r);
  const assetHandler=async route=>{assetObserved();await assetHeld;try{await route.continue()}catch(error){if(!closing)throw error}};await page.route('**/assets/hpoint-workflows.js*',assetHandler);
  await page.reload({waitUntil:'commit'});await assetSeen;await page.waitForTimeout(650);
  assert.equal(await page.locator('#hpointWorkspace').isVisible(),false);assert.equal(await page.locator('#landing').isVisible(),false);assert.equal(await page.locator('#globalBalance').isVisible(),false);checks+=3;
  const during=await page.evaluate(()=>window.qaHeaderFrames);assert.deepEqual(during.oldHeader,[]);assert.deepEqual(during.legacyPanels,[]);assert.deepEqual(during.earlyLanding,[]);checks+=3;
  releaseAsset();await page.locator('#hpointWorkspace').waitFor();await page.locator('.workspaceBillingGrid').waitFor();await refresh();
  const after=await page.evaluate(()=>window.qaHeaderFrames);assert.deepEqual(after.oldHeader,[]);assert.deepEqual(after.legacyPanels,[]);assert.deepEqual(after.earlyLanding,[]);assert.equal(after.oldHeaderWrites,0);checks+=4;
  await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'stable-header-billing.png'),fullPage:true});
  for(const asset of ['hpoint-support.js','hpoint-profile.js']){
   const pattern='**/assets/'+asset+'*',failure=route=>route.abort();await page.route(pattern,failure);await page.reload({waitUntil:'domcontentloaded'});await page.getByText('Не удалось загрузить H-Point',{exact:true}).waitFor();
   assert.equal(await page.locator('#hpointWorkspace').isVisible(),false);assert.equal(await page.locator('#landing').isVisible(),false);assert.equal(await page.locator('#hpointBootScreen').getByRole('button',{name:'Повторить',exact:true}).isVisible(),true);checks+=3;
   await page.unroute(pattern,failure);await page.reload();await page.locator('#hpointWorkspace').waitFor();checks++;
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,headerStable:true,noLegacyHeaderWrites:true,delayedBillingStable:true,walletUpdateStable:true,coldLoadNoFlash:true,failedNewModulesRecover:true}));
 }finally{closing=true;releaseBilling?.();releaseAsset?.();await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
