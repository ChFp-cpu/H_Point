/* Real workspace controls, synthetic users and a disposable local server. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {openHelpTab}=require('./help_navigation.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket,width){const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await emailLogin(page,ticket);await page.evaluate(()=>closeModal());return {context,page}}
 async function get(a,url){const r=await a.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(a,url,data){const r=await a.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function match(author,rid){await author.page.goto(base+'/#/help');await author.page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(author.page,'match');await author.page.locator('#wsMatchRequest').selectOption(String(rid));await author.page.locator('[data-ws-action="match-load"]').click();await author.page.waitForFunction(()=>Boolean(hpointWorkspace.state.matches));}
 try{
  const author=await actor('theme-browser-data',1440),first=await actor('mobile-helper',390),second=await actor('theme-browser-empty',390);
  const request=(await get(author,'/api/sync')).requests.find(r=>r.status==='open'&&r.category==='tech'),rid=request.id;
  await post(first,'/api/helper/preferences',{categories:['carry'],ready:false,radius_km:0});
  await first.page.evaluate(()=>hpointWorkspace.refresh());
  await first.page.locator('.homeHero [data-ws-action="queue"]').click();
  await first.page.locator('#hpEnterHelper').click();
  await first.page.waitForFunction(()=>Boolean(hpointWorkspace.state.data?.user.helper_ready));
  assert.equal((await get(first,'/api/sync')).user.helper_ready,true);checks++;
  await match(author,rid);assert.equal(await author.page.locator('.workspaceCandidate [data-user="904"]').count(),0);checks++;
  await first.page.goto(base+'/#/help');await openHelpTab(first.page,'open');
  await first.page.locator('[data-ws-action="help-tab"][data-tab="preferences"]').first().click();
  await first.page.locator('[name="helperCategory"][value="carry"]').uncheck();await first.page.locator('[name="helperCategory"][value="tech"]').check();
  await first.page.locator('[data-ws-action="helper-preferences-save"]').click();await first.page.locator('#helperPreferencesStatus').filter({hasText:'Сохранено'}).waitFor();
  await first.page.reload();await first.page.waitForFunction(()=>Boolean(hpointWorkspace.state.data));
  assert.deepEqual((await get(first,'/api/sync')).user.helper_categories,['tech']);checks++;
  await post(first,'/api/profile',{bio:'Настроить домашнюю технику. Ремонт ноутбуков.'});
  await post(second,'/api/helper/preferences',{categories:[],ready:true,radius_km:0});
  await match(author,rid);
  const recommended=author.page.locator('.workspaceCandidate').filter({has:author.page.locator('[data-user="904"]')});
  const percentage=await recommended.locator('.workspaceMatchPercent').innerText();
  assert.match(percentage,/\b(?:100|[1-9]?\d)%/);
  assert.match(await recommended.locator('.workspaceMatchFactors').innerText(),/Техника/i);
  assert.match(await recommended.locator('.workspaceMatchFactors').innerText(),/настроить|домашнюю|технику/i);
  assert.equal(await author.page.locator('.workspaceCandidate [data-user="905"]').count(),0);checks+=4;

  const requirements=author.page.locator('#wsMatchQuestion');
  await requirements.evaluate(input=>{input.value='qa901@example.test';input.dispatchEvent(new Event('input',{bubbles:true}));});
  const manualSearch=author.page.waitForRequest(request=>request.url().endsWith('/api/assistant/candidates')&&request.postDataJSON()?.mode==='manual');
  await author.page.locator('[data-ws-action="match-load-manual"]').click();
  const manualPayload=(await manualSearch).postDataJSON();
  assert.equal(manualPayload.question,'');
  await author.page.waitForFunction(()=>hpointWorkspace.state.matches?.mode==='manual');
  assert.equal(await requirements.inputValue(),'');
  assert.equal(await author.page.locator('.workspaceCandidate [data-user="905"]').count(),1);checks+=3;

  await requirements.fill('ремонт ноутбуков');
  const filteredSearch=author.page.waitForRequest(request=>request.url().endsWith('/api/assistant/candidates')&&request.postDataJSON()?.question==='ремонт ноутбуков');
  await author.page.locator('[data-ws-action="match-load"]').click();
  assert.equal((await filteredSearch).postDataJSON().mode,'recommended');
  await author.page.waitForFunction(()=>hpointWorkspace.state.matches?.mode==='recommended');
  assert.equal(await recommended.count(),1);checks+=2;
  await requirements.fill('');
  await post(second,'/api/helper/preferences',{categories:['tech'],ready:true,radius_km:0});
  await match(author,rid);
  for(const uid of [904,905])assert.equal(await author.page.locator('.workspaceCandidate [data-user="'+uid+'"]').count(),1);
  assert.equal(await author.page.locator('.workspaceCandidate [data-user="902"]').count(),0);checks+=3;
  await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'smart-match-desktop.png'),fullPage:true});
  await author.page.setViewportSize({width:320,height:900});
  assert.equal(await author.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await recommended.locator('.workspaceMatchPercent').isVisible(),true);checks+=2;
  await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'smart-match-results-320.png'),fullPage:true});
  await author.page.setViewportSize({width:1440,height:900});
  for(const uid of [904,905]){await author.page.locator('.workspaceCandidate [data-user="'+uid+'"]').click();await author.page.waitForFunction(uid=>hpointWorkspace.state.matches?.matches.some(r=>r.user_id===uid&&r.status==='offered'),uid);}
  assert.equal((await get(author,'/api/sync')).outgoing_offers.length,2);checks++;
  const chats=[];
  for(const helper of [first,second]){
   await helper.page.evaluate(()=>hpointWorkspace.refresh());
   await helper.page.locator('[data-ws-action="offer"][data-id="'+rid+'"][data-accept="true"]').first().click();
   await helper.page.waitForFunction(rid=>hpointWorkspace.state.chat?.request_id===rid,rid);
   const chat=await helper.page.evaluate(()=>hpointWorkspace.state.chat);chats.push(chat.id);
   assert.equal(chat.status,'open');assert.equal(chat.can_complete,false);checks+=2;
   await helper.page.locator('#wsChatText').fill('Готов обсудить задачу');await helper.page.locator('#wsChatText').press('Enter');
   await helper.page.waitForFunction(()=>document.getElementById('wsChatText')?.value==='');
  }
  assert.notEqual(chats[0],chats[1]);checks++;
  await match(author,rid);const select=author.page.locator('.workspaceCandidate [data-user="904"]');assert.equal(await select.textContent(),'Выбрать исполнителя');checks++;
  author.page.once('dialog',d=>d.accept());await select.click();await author.page.waitForFunction(rid=>hpointWorkspace.state.chat?.request_id===rid&&hpointWorkspace.state.chat.status==='in_progress',rid);
  const chosen=await author.page.evaluate(()=>hpointWorkspace.state.chat);assert.equal(chosen.id,chats[0]);assert.equal(chosen.can_complete,true);assert.equal(chosen.messages[0].text,'Готов обсудить задачу');checks+=3;
  const ready=(await get(first,'/api/sync')).user;assert.equal(ready.helper_ready,true);assert.equal(ready.helper_busy,true);checks+=2;
  await first.page.goto(base+'/#/help');await first.page.evaluate(()=>hpointWorkspace.refresh());await openHelpTab(first.page,'open');
  await first.page.getByText('Выполняете помощь',{exact:true}).waitFor();
  await first.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'smart-match-mobile.png'),fullPage:true});
  assert.equal((await get(second,'/api/chats?chat_id='+chats[1])).chats[0].can_send,false);checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,readinessPersisted:true,categoryFilter:true,busyExcluded:true,parallelInvites:true,privateChats:true,requesterOnlySelection:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
