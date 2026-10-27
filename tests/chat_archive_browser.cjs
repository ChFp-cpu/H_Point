/* Archive privacy and delayed-response races; synthetic localhost data only. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0,release;
 async function actor(ticket){const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await emailLogin(page,ticket);return {context,page}}
 async function get(a,url){const r=await a.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(a,url,data){const r=await a.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function create(a,what){return (await post(a,'/api/requests',{what,place:'Synthetic district',time_needed:'today',urgency:'normal',category:'tech',details:'Synthetic QA only'})).request_id}
 async function open(a,rid,cid){await a.page.bringToFront();await a.page.evaluate(({rid,cid})=>hpointWorkspace.openChat(rid,cid),{rid,cid});await a.page.waitForFunction(cid=>Number(hpointWorkspace.state.threadId)===cid&&Boolean(hpointWorkspace.state.chat),cid);await a.page.locator('#wsChatText').waitFor()}
 async function switchAccount(a,uid){await post(a,'/api/auth/login',{email:'qa'+uid+'@example.test',password:'SyntheticQa1'});await a.page.evaluate(()=>window.load());await a.page.waitForFunction(uid=>Number(hpointWorkspace.state.data?.current_user_id)===uid,uid)}
 async function closed(a){const details=a.page.locator('.chatArchivedList');if(await details.getAttribute('open')!==null)await details.locator('summary').click();await details.locator('summary').click();await a.page.waitForFunction(()=>hpointWorkspace.state.showClosedChats===true);await a.page.locator('.chatArchivedList[open]').waitFor()}
 async function captureResponse(a,url,act){
  let release,observed,fulfilled;const gate=new Promise(r=>release=r),seen=new Promise(r=>observed=r),done=new Promise(r=>fulfilled=r);
  const handler=async route=>{const response=await route.fetch();observed();await gate;try{await route.fulfill({response})}finally{fulfilled()}};
  await a.page.route(base+url,handler);await act();await seen;
  return async()=>{release();await done;await a.page.unroute(base+url,handler)};
 }
 try{
  const author=await actor('theme-browser-data'),helper=await actor('mobile-helper'),other=await actor('theme-browser-empty'),page=author.page;
  const first=await create(author,'Private archived help A'),second=await create(author,'Independent help B');
  await post(helper,'/api/requests/apply',{request_id:first});await post(other,'/api/requests/apply',{request_id:second});
  const ca=(await get(helper,'/api/chats?request_id='+first)).chats[0].id,cb=(await get(other,'/api/chats?request_id='+second)).chats[0].id;
  await post(helper,'/api/chats/send',{request_id:first,chat_id:ca,text:'Private archived message A'});await page.evaluate(()=>hpointWorkspace.refresh());
  await open(author,first,ca);
  release=await captureResponse(author,'/api/chats/archive',()=>page.locator('[data-ws-action="chat-archive"]').click());
  await open(author,second,cb);await page.locator('#wsChatText').fill('Draft in B survives archive A');await release();await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.threadId),cb);assert.equal(await page.locator('#wsChatText').inputValue(),'Draft in B survives archive A');assert.ok(!(await get(author,'/api/chats')).chats.some(c=>c.id===ca));checks+=3;
  await closed(author);await page.waitForFunction(cid=>hpointWorkspace.state.archivedChats?.some(c=>c.id===cid),ca);assert.match(await page.locator('.chatArchivedList').innerText(),/Private archived message A/);checks++;
  await post(helper,'/api/chats/send',{request_id:first,chat_id:ca,text:'Incoming reopens help A'});await page.evaluate(()=>hpointWorkspace.refresh());
  assert.ok(await page.evaluate(cid=>hpointWorkspace.state.data.chats.some(c=>c.id===cid),ca));assert.ok(!(await page.evaluate(cid=>hpointWorkspace.state.archivedChats?.some(c=>c.id===cid),ca)));assert.equal(await page.locator('.chatArchivedList [data-ws-action="chat"][data-thread="'+ca+'"]').count(),0);checks+=3;
  await post(author,'/api/chats/archive',{chat_id:ca});await page.evaluate(()=>hpointWorkspace.refresh());await closed(author);await page.waitForFunction(cid=>hpointWorkspace.state.archivedChats?.some(c=>c.id===cid),ca);
  await page.evaluate(async()=>{const result=await api('/api/auth/link-code',{method:'POST',body:'{}'});hpointWorkspace.state.linkCode=result.code;hpointWorkspace.state.helpTab='preferences';window.go('help')});
  await page.locator('#helperPreferencesForm').waitFor();await page.locator('.helperAdvanced summary').click();
  await page.locator('#wsHelperAvailability').fill('Private unsaved helper note A');await page.locator('#wsHelperRadius').fill('13');await page.locator('#wsHelperCategory_tech').check();await page.locator('#wsHelperReady').check();
  await page.evaluate(()=>window.qaOldHelperForm=document.getElementById('helperPreferencesForm'));
  await switchAccount(author,905);
  assert.deepEqual(await page.evaluate(()=>hpointWorkspace.state.archivedChats||[]),[]);assert.equal(await page.evaluate(()=>Boolean(hpointWorkspace.state.showClosedChats)),false);assert.equal(await page.getByText('Private archived help A',{exact:false}).count(),0);checks+=3;
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.linkCode),'');assert.equal(await page.locator('#helperPreferencesForm').evaluate(e=>e===window.qaOldHelperForm),false);assert.equal(await page.locator('#wsHelperAvailability').inputValue(),'');assert.equal(await page.locator('#wsHelperRadius').inputValue(),'0');assert.equal(await page.locator('#wsHelperCategory_tech').isChecked(),false);assert.equal(await page.locator('#wsHelperReady').isChecked(),false);checks+=6;
  await switchAccount(author,901);await open(author,second,cb);
  await page.evaluate(()=>{const original=window.api;window.qaClosedAPISettled=0;window.api=async function(url,...args){try{return await original.call(this,url,...args)}finally{if(String(url)==='/api/chats?archived=1')window.qaClosedAPISettled++}}});
  release=await captureResponse(author,'/api/chats?archived=1',()=>page.locator('.chatArchivedList summary').click());
  await switchAccount(author,905);await open(author,second,cb);await release();await page.waitForFunction(()=>window.qaClosedAPISettled>0);
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.data.current_user_id),905);assert.deepEqual(await page.evaluate(()=>hpointWorkspace.state.archivedChats||[]),[]);assert.equal(await page.getByText('Private archived help A',{exact:false}).count(),0);checks+=3;
  await switchAccount(author,901);await open(author,first,ca);
  release=await captureResponse(author,'/api/chats/archive',()=>page.locator('[data-ws-action="chat-archive"]').click());
  await switchAccount(author,905);await open(author,second,cb);await page.locator('#wsChatText').fill('New account draft B');await release();await page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.data.current_user_id),905);assert.equal(await page.evaluate(()=>hpointWorkspace.state.threadId),cb);assert.equal(await page.locator('#wsChatText').inputValue(),'New account draft B');assert.deepEqual(await page.evaluate(()=>hpointWorkspace.state.archivedChats||[]),[]);checks+=4;
  await switchAccount(author,901);await open(author,second,cb);await closed(author);await page.waitForFunction(cid=>hpointWorkspace.state.archivedChats?.some(c=>c.id===cid),ca);
  await page.evaluate(async()=>{const result=await api('/api/auth/link-code',{method:'POST',body:'{}'});hpointWorkspace.state.linkCode=result.code;await api('/api/auth/logout',{method:'POST',body:'{}'});window.landing()});
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.data),null);assert.deepEqual(await page.evaluate(()=>hpointWorkspace.state.archivedChats||[]),[]);assert.equal(await page.evaluate(()=>Boolean(hpointWorkspace.state.showClosedChats)),false);assert.equal(await page.evaluate(()=>hpointWorkspace.state.linkCode),'');checks+=4;
  await switchAccount(author,905);await open(author,second,cb);await closed(author);assert.equal(await page.locator('.chatArchivedList [data-ws-action="chat"][data-thread="'+ca+'"]').count(),0);assert.equal(await page.getByText('Private archived help A',{exact:false}).count(),0);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,archiveSwitchChatSafe:true,archiveIncomingDeduplicated:true,archiveOwnerChangePrivate:true,delayedArchiveListPrivate:true,delayedArchiveActionPrivate:true,logoutClearsArchives:true,helperFormOwnerPrivate:true,linkCodeOwnerPrivate:true}));
 }finally{await release?.().catch(()=>{});for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
