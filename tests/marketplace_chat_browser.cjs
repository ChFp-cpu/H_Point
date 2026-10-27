/* Multiple responses, private conversations and request actions; synthetic accounts. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function actor(ticket){const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept(d.type()==='prompt'?'Планы изменились':undefined));await emailLogin(page,ticket);return {context,page}}
 async function get(a,url){const r=await a.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(a,url,data){const r=await a.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function create(a,what){return (await post(a,'/api/requests',{what,place:'Тестовый район',time_needed:'сегодня',urgency:'обычная',category:'tech',details:'Только синтетические данные'})).request_id}
 async function apply(a,rid){await post(a,'/api/requests/apply',{request_id:rid});return (await get(a,'/api/chats?request_id='+rid)).chats[0].id}
 async function open(a,rid,cid){await a.page.bringToFront();await a.page.evaluate(({rid,cid})=>hpointWorkspace.openChat(rid,cid),{rid,cid});await a.page.locator('.workspaceChatPanel').waitFor();await a.page.waitForFunction(cid=>Number(hpointWorkspace.state.threadId)===cid&&Boolean(hpointWorkspace.state.chat),cid)}
 async function mutation(a,selector,endpoint){const response=a.page.waitForResponse(r=>r.url()===base+endpoint&&r.request().method()==='POST');await a.page.locator(selector).click();assert.equal((await response).status(),200);await a.page.evaluate(()=>hpointWorkspace.refresh())}
 async function delayedSend(a,send){let release,observed,continued;const gate=new Promise(r=>release=r),seen=new Promise(r=>observed=r),handled=new Promise(r=>continued=r);const handler=async route=>{if(route.request().method()!=='POST')return route.continue();observed();await gate;try{await route.continue()}finally{continued()}};await a.page.route(base+'/api/chats/send',handler);await send();await seen;return async()=>{release();await handled;await a.page.unroute(base+'/api/chats/send',handler)}}
 try{
  const author=await actor('theme-browser-data'),a=await actor('mobile-helper'),b=await actor('theme-browser-empty'),page=author.page;
  const rid=await create(author,'Помощь с несколькими откликами'),next=await create(author,'Вторая помощь для того же помощника');
  const first=await apply(a,rid),second=await apply(b,rid),later=await apply(a,next);
  assert.notEqual(first,second);assert.equal((await get(a,'/api/sync')).my_applications.length,2);assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===rid).status,'open');checks+=3;
  await page.evaluate(()=>hpointWorkspace.refresh());await open(author,rid,first);
  const layout=await page.evaluate(()=>{const panel=document.querySelector('.workspaceChatPanel'),list=document.querySelector('.chatListCard');return {before:Boolean(panel.compareDocumentPosition(list)&Node.DOCUMENT_POSITION_FOLLOWING),panel:panel.getBoundingClientRect().bottom,list:list.getBoundingClientRect().top}});
  assert.equal(layout.before,true);assert.ok(layout.panel<=layout.list+1);checks+=2;
  const field=page.locator('#wsChatText'),picker=()=>page.locator('.workspaceChatForm .hpointPhotoPicker input'),previews=()=>page.locator('.workspaceChatForm .hpointPhotoPreviews img');
  const photo=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=40;c.height=30;c.getContext('2d').fillRect(0,0,40,30);return c.toDataURL('image/png')});
  const file={name:'synthetic-private.png',mimeType:'image/png',buffer:Buffer.from(photo.split(',')[1],'base64')};
  await field.fill('Черновик помощника А');await picker().setInputFiles(file);await previews().waitFor();
  await open(author,rid,second);assert.equal(await field.inputValue(),'');assert.equal(await previews().count(),0);checks+=2;
  await field.fill('Черновик помощника Б');await picker().setInputFiles(file);await previews().waitFor();
  await open(author,rid,first);assert.equal(await field.inputValue(),'Черновик помощника А');assert.equal(await previews().count(),1);checks+=2;
  await field.fill('Фото только для помощника А');let release=await delayedSend(author,()=>field.press('Enter'));
  await open(author,rid,second);await release();await page.waitForFunction(()=>hpointWorkspace.state.chatSending===false);
  assert.equal(await page.evaluate(()=>hpointWorkspace.state.threadId),second);assert.equal(await field.inputValue(),'Черновик помощника Б');assert.equal(await previews().count(),1);checks+=3;
  let chat=(await get(author,'/api/chats?chat_id='+first)).chats[0];const sent=chat.messages.filter(m=>m.text==='Фото только для помощника А');assert.equal(sent.length,1);assert.equal(sent[0].photos.length,1);checks+=2;
  assert.equal((await b.context.request.get(base+'/api/chats?chat_id='+first)).status(),403);assert.equal((await b.context.request.get(base+sent[0].photos[0].url)).status(),403);checks+=2;
  await field.fill('Первая строка');await field.press('Shift+Enter');await page.keyboard.insertText('Б');assert.equal(await field.inputValue(),'Первая строка\nБ');checks++;
  await field.press('Enter');await page.waitForFunction(()=>document.getElementById('wsChatText')?.value==='');
  chat=(await get(b,'/api/chats?chat_id='+second)).chats[0];assert.equal(chat.messages.filter(m=>m.text==='Первая строка\nБ').length,1);assert.equal(chat.messages[0].photos.length,1);checks+=2;
  await open(author,rid,first);
  const started=Date.now();await post(a,'/api/chats/send',{request_id:rid,chat_id:first,text:'Быстрое входящее сообщение'});await page.locator('.workspaceMessages').getByText('Быстрое входящее сообщение').waitFor({timeout:2000});
  const arrival=Date.now()-started;assert.ok(arrival<=1500,'Incoming message took '+arrival+'ms');checks++;
  await field.fill('Черновик не должен исчезнуть');await field.evaluate(e=>{window.qaChatComposer=e;e.focus();e.setSelectionRange(2,8)});
  await page.evaluate(()=>{window.qaChatMutations=0;window.qaChatObserver=new MutationObserver(records=>window.qaChatMutations+=records.length);window.qaChatObserver.observe(document.getElementById('hpointWorkspace'),{childList:true})});
  await page.waitForTimeout(8500);assert.equal(await page.evaluate(()=>window.qaChatMutations),0);assert.equal(await field.evaluate(e=>e===window.qaChatComposer),true);assert.equal(await field.inputValue(),'Черновик не должен исчезнуть');assert.deepEqual(await field.evaluate(e=>({focused:document.activeElement===e,start:e.selectionStart,end:e.selectionEnd})),{focused:true,start:2,end:8});await page.evaluate(()=>window.qaChatObserver.disconnect());checks+=4;
  await mutation(author,'[data-ws-action="chat-archive"]','/api/chats/archive');assert.ok(!(await get(author,'/api/chats')).chats.some(c=>c.id===first));assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===rid).status,'open');checks+=2;
  await page.locator('.chatArchivedList summary').click();await mutation(author,'[data-ws-action="chat-restore"][data-thread="'+first+'"]','/api/chats/restore');assert.ok((await get(author,'/api/chats')).chats.some(c=>c.id===first));checks++;
  await open(author,rid,first);await mutation(author,'[data-ws-action="chat-archive"]','/api/chats/archive');
  await post(a,'/api/chats/send',{request_id:rid,chat_id:first,text:'Новое сообщение возвращает чат'});await page.evaluate(()=>hpointWorkspace.refresh());assert.ok((await get(author,'/api/chats')).chats.some(c=>c.id===first));checks++;
  await open(author,rid,first);await page.locator('[data-ws-action="chat-select"]').click();
  await page.waitForFunction(rid=>hpointWorkspace.state.data.requests.some(r=>r.id===rid&&r.status==='in_progress'),rid);
  assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===rid).helper_id,904);assert.equal((await get(b,'/api/chats?chat_id='+second)).chats[0].can_send,false);checks+=2;
  await open(a,rid,first);assert.equal(await a.page.locator('.workspaceChatPanel [data-ws-action="finish"]').count(),0);assert.equal(await a.page.locator('[data-ws-action="chat-cancel"]').isVisible(),true);checks+=2;
  await open(author,rid,first);await page.locator('.workspaceChatPanel [data-ws-action="finish"]').click();
  await page.waitForFunction(rid=>hpointWorkspace.state.data.requests.some(r=>r.id===rid&&r.status==='done'),rid);checks++;
  await page.locator('#hpSendReview').waitFor();await page.locator('#hpSendReview').click();await page.locator('#modal').waitFor({state:'hidden'});checks++;
  await a.page.bringToFront();await a.page.evaluate(()=>hpointWorkspace.refresh());await a.page.locator('#hpSendReview').waitFor();await a.page.locator('#hpSendReview').click();await a.page.locator('#modal').waitFor({state:'hidden'});checks++;
  await open(author,next,later);await page.locator('[data-ws-action="chat-select"]').click();await page.waitForFunction(rid=>hpointWorkspace.state.data.requests.some(r=>r.id===rid&&r.status==='in_progress'),next);
  await open(a,next,later);await a.page.evaluate(()=>closeModal());await a.page.locator('[data-ws-action="chat-cancel"]').click();
  await a.page.waitForFunction(rid=>hpointWorkspace.state.chat?.request_id===rid&&hpointWorkspace.state.chat?.status==='cancelled',next);assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===next).status,'cancelled');checks++;
  const last=await create(author,'Отмена автором из обсуждения'),lastChat=await apply(b,last);await open(b,last,lastChat);await b.page.locator('[data-ws-action="chat-withdraw"]').click();
  await b.page.waitForFunction(cid=>hpointWorkspace.state.chat?.id===cid&&hpointWorkspace.state.chat?.can_send===false,lastChat);
  assert.equal((await get(author,'/api/sync')).requests.find(r=>r.id===last).status,'open');assert.ok(!(await get(b,'/api/sync')).my_applications.some(r=>r.request_id===last));checks+=2;
  assert.equal(await apply(b,last),lastChat);checks++;await page.evaluate(()=>hpointWorkspace.refresh());await open(author,last,lastChat);await page.locator('[data-ws-action="chat-cancel"]').click();
  await page.waitForFunction(rid=>hpointWorkspace.state.data.requests.some(r=>r.id===rid&&r.status==='cancelled'),last);checks++;
  await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'marketplace-chat-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,checks,errors,multipleResponses:true,privateCandidateChats:true,separateDraftsAndPhotos:true,enterSend:true,shiftEnterNewline:true,arrivalMs:arrival,idleDomStable:true,archiveReopens:true,requestActionsBothSides:true}));
 }catch(error){console.error('Marketplace errors:',errors);throw error}finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
