/* Live theme transitions must update surfaces, icons and readable text together. */
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local synthetic QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[];let checks=0;
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 async function audit(scheme,label){
  const data=await page.evaluate(()=>{
   const rgb=value=>{const match=value.match(/^rgba?\(([^)]+)\)$/);if(!match)return null;const parts=match[1].split(',').map(Number);return {r:parts[0],g:parts[1],b:parts[2],a:parts.length===4?parts[3]:1}};
   const luminance=c=>[c.r,c.g,c.b].map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   const bg=node=>{for(let n=node;n;n=n.parentElement){const c=rgb(getComputedStyle(n).backgroundColor);if(c&&c.a>.95)return c}return rgb(getComputedStyle(document.documentElement).backgroundColor)};
   const visible=node=>node.getBoundingClientRect().width>0&&node.getBoundingClientRect().height>0&&getComputedStyle(node).visibility!=='hidden';
   const surfaces=[...document.querySelectorAll('.workspaceCard,.workspaceMetric,.workspaceAccountNav,.workspaceRequest,.workspaceProduct,.workspaceChatButton,.leagueBoard,.leagueRow,.duoChampionCard,.duoAvatar,.duoRankBadge,.leagueAvatar,.leagueTrophy,.leagueHeadingMark,.commercialCard,.commercialRow,.commercialMetric,.box,.avatar,.workspaceCandidateAvatar,.workspaceLeaderAvatar')].filter(visible).map(node=>({name:node.className,bg:getComputedStyle(node).backgroundColor,image:getComputedStyle(node).backgroundImage,light:luminance(bg(node)),shadow:getComputedStyle(node).boxShadow}));
   const text=[...document.querySelectorAll('.workspaceSubtitle,.workspaceInfoRow>span,.workspaceAccountNav button,.duoChampionMeta,.leagueMemberMeta,#sitePrimaryNav button,.commercialHelp,.commercialMetric span')].filter(visible).map(node=>{const c=rgb(getComputedStyle(node).color),back=bg(node),a=luminance(c),b=luminance(back);return {name:node.className||node.tagName,text:node.textContent.slice(0,55),contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),opacity:getComputedStyle(node).opacity}});
   return{surfaces,text,overflow:document.documentElement.scrollWidth>innerWidth+1,primary:getComputedStyle(document.documentElement).getPropertyValue('--hp-text-primary'),secondary:getComputedStyle(document.documentElement).getPropertyValue('--hp-text-secondary')};
  });
  assert.equal(data.overflow,false,label+' overflow');checks++;
  if(scheme==='light'){assert.deepEqual(data.surfaces.filter(node=>node.light<.65),[],label+' dark surfaces');checks++}
  else {assert.deepEqual(data.surfaces.filter(node=>node.light>.4),[],label+' stale light surfaces');checks++}
  assert.deepEqual(data.surfaces.filter(node=>/leagueTrophy|leagueHeadingMark/.test(node.name)&&node.shadow!=='none'),[],label+' heavy icon shadows');checks++;
  assert.deepEqual(data.text.filter(node=>node.contrast<4.49||Number(node.opacity)<1),[],label+' faint text');checks++;
 }
 try{
  await emailLogin(page,'theme-browser-data');await page.evaluate(()=>hpointWorkspace.refresh());
  await page.goto(base+'/#/profile');await page.locator('#workspaceWorkCreationSlot').getByRole('button',{name:'Создать кабинет в профиле',exact:true}).click();
  const profile=page.locator('[data-commercial-form=profile]');await profile.locator('[name=kind]').selectOption('organization');await profile.locator('[name=title]').fill('Контрастная тестовая организация');await profile.locator('[name=contact]').press('Enter');await page.waitForURL('**/#/work');await page.locator('.commercialTabs').waitFor();
  const routes=['home','help','profile','profile/wallet','profile/billing','activities','league','work'];
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:1000});
   for(const route of routes){
    await page.goto(base+'/#/'+route);await page.locator('#hpointWorkspace').waitFor();await page.evaluate(()=>hpointWorkspace.refresh());
    if(route==='league')await page.locator('.duoChampionCard').waitFor();if(route==='work')await page.locator('.commercialTabs').waitFor();
    const current=await page.locator('#hpointWorkspace').elementHandle();
    for(const scheme of ['dark','light','dark','light']){
     await page.emulateMedia({colorScheme:scheme});await audit(scheme,width+' '+route+' '+scheme);
     assert.equal(await current.evaluate(node=>node===document.getElementById('hpointWorkspace')),true,'Theme switch keeps the workspace');checks++;
    }
    if(route==='league'&&[390,1440].includes(width))await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'theme-contrast-league-'+width+'.png'),fullPage:true});
   }
  }
  await page.goto(base+'/#/home');await page.evaluate(()=>requestForm());await page.locator('#qw').waitFor();
  for(const scheme of ['dark','light']){await page.emulateMedia({colorScheme:scheme});await audit(scheme,'request modal '+scheme)}await page.evaluate(()=>closeModal());
  await page.evaluate(()=>openSupport());await page.locator('#modal').waitFor({state:'visible'});for(const scheme of ['dark','light']){await page.emulateMedia({colorScheme:scheme});await audit(scheme,'support modal '+scheme)}await page.evaluate(()=>closeModal());
  await page.goto(base+'/#/league');await page.evaluate(()=>openCommunityProfile(901));await page.locator('.communityProfile').waitFor();for(const scheme of ['dark','light']){await page.emulateMedia({colorScheme:scheme});await audit(scheme,'community profile '+scheme)}await page.evaluate(()=>closeModal());
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,liveThemeSurfaces:true,readableSecondaryText:true,quietLeagueIcons:true}));
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
