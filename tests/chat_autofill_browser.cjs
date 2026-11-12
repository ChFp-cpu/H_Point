/* Chat composer regressions; synthetic local email profiles only. */
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');

(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await emailLogin(page,ticket);return {context,page};
 }
 async function get(actor,url){const r=await actor.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
 async function post(actor,url,data){const r=await actor.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 async function open(actor,id){await actor.page.evaluate(id=>hpointWorkspace.openChat(id),id);await actor.page.locator('textarea#wsChatText').waitFor()}
 async function delayedSend(actor,send){
  let release,observed,continued;
  const gate=new Promise(resolve=>release=resolve),seen=new Promise(resolve=>observed=resolve),handled=new Promise(resolve=>continued=resolve);
  const handler=async route=>{if(route.request().method()!=='POST')return route.continue();observed();await gate;try{await route.continue()}finally{continued()}};
  await actor.page.route(base+'/api/chats/send',handler);
  await send();await seen;
  return async()=>{release();await handled;await actor.page.unroute(base+'/api/chats/send',handler)};
 }
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  const before=await get(author,'/api/sync'),second=before.requests.find(r=>r.status==='in_progress').id;
  const first=before.requests.find(r=>r.status==='open').id;
  await post(helper,'/api/requests/accept',{request_id:first});await author.page.evaluate(()=>hpointWorkspace.refresh());
  await open(author,first);
  const field=author.page.locator('#wsChatText');
  assert.equal(await field.evaluate(e=>e.tagName),'TEXTAREA');
  assert.equal(await field.getAttribute('autocomplete'),'off');
  assert.match(await field.getAttribute('name'),/message|chat/i);checks+=3;
  await field.fill('Черновик первого чата');
  await field.evaluate(e=>{window.qaOriginalComposer=e;e.setSelectionRange(3,8)});
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await field.evaluate(e=>e===window.qaOriginalComposer),true,'Regular sync preserves the message element');
  assert.equal(await field.inputValue(),'Черновик первого чата');checks+=2;
  await post(helper,'/api/chats/send',{request_id:first,text:'Новое входящее сообщение'});
  await author.page.locator('.workspaceMessages').getByText('Новое входящее сообщение',{exact:false}).waitFor();
  assert.equal(await field.evaluate(e=>e===window.qaOriginalComposer),true,'Incoming-message polling preserves the message element');
  assert.equal(await field.inputValue(),'Черновик первого чата');checks+=2;
  await open(author,second);assert.equal(await field.inputValue(),'','Draft must not migrate to another conversation');checks++;
  await field.fill('Черновик второго чата');await open(author,first);assert.equal(await field.inputValue(),'Черновик первого чата');
  await open(author,second);assert.equal(await field.inputValue(),'Черновик второго чата');checks+=2;

  // A workspace sync may finish while POST is pending. Its old draft must not
  // come back after the successful send, nor cause a second POST.
  await open(author,first);await field.fill('Сообщение с задержанной отправкой');
  let release=await delayedSend(author,()=>author.page.locator('[data-ws-action="chat-send"]').click());
  await author.page.evaluate(()=>hpointWorkspace.refresh());await release();
  await author.page.waitForFunction(()=>document.getElementById('wsChatText')?.value==='');
  await author.page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await field.inputValue(),'');
  let chat=(await get(author,'/api/chats?request_id='+first)).chats[0];
  assert.equal(chat.messages.filter(m=>m.text==='Сообщение с задержанной отправкой').length,1);checks+=2;

  // Text typed after clicking Send belongs to the next message. A response
  // to the preceding POST must preserve that newer draft.
  await field.fill('Первое сообщение перед новым черновиком');
  release=await delayedSend(author,()=>author.page.locator('[data-ws-action="chat-send"]').click());
  await field.fill('Следующий черновик во время отправки');
  await author.page.evaluate(()=>hpointWorkspace.refresh());await release();
  await author.page.waitForFunction(()=>hpointWorkspace.state.chatSending===false);
  assert.equal(await field.inputValue(),'Следующий черновик во время отправки');
  chat=(await get(author,'/api/chats?request_id='+first)).chats[0];
  assert.equal(chat.messages.filter(m=>m.text==='Первое сообщение перед новым черновиком').length,1);
  assert.equal(chat.messages.filter(m=>m.text==='Следующий черновик во время отправки').length,0);checks+=3;

  // If the user opens B before A's send response, A's response must not
  // replace B's messages or draft and must not force a return to A.
  await field.fill('Этот ответ принадлежит первому чату');
  release=await delayedSend(author,()=>author.page.locator('[data-ws-action="chat-send"]').click());
  await open(author,second);await release();
  await author.page.waitForFunction(()=>hpointWorkspace.state.chatSending===false);
  assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.chatId),second);
  assert.equal(await field.inputValue(),'Черновик второго чата');
  assert.equal(await author.page.locator('.workspaceMessages').getByText('Этот ответ принадлежит первому чату',{exact:true}).count(),0);checks+=3;
  await open(author,first);assert.equal(await field.inputValue(),'');checks++;

  // A participant can deliberately share an email as message content. This
  // fix must not strip or reject legitimate text resembling saved credentials.
  await field.fill('contact@example.test');await author.page.locator('[data-ws-action="chat-send"]').click();
  await author.page.waitForFunction(()=>document.getElementById('wsChatText')?.value==='');
  chat=(await get(author,'/api/chats?request_id='+first)).chats[0];
  assert.equal(chat.messages.filter(m=>m.text==='contact@example.test').length,1);checks++;

  // Photo sends use the same composer transaction. A delayed A response
  // must leave both B's text and B's independently selected photos intact.
  await author.page.waitForFunction(()=>Boolean(window.HPointMedia));
  const photo=await author.page.evaluate(()=>{const c=document.createElement('canvas');c.width=40;c.height=30;const g=c.getContext('2d');g.fillStyle='#b8f36b';g.fillRect(0,0,40,30);return c.toDataURL('image/png')});
  const file={name:'synthetic-chat.png',mimeType:'image/png',buffer:Buffer.from(photo.split(',')[1],'base64')};
  const photoPicker=()=>author.page.locator('.workspaceChatForm .hpointPhotoPicker input');
  const previews=()=>author.page.locator('.workspaceChatForm .hpointPhotoPreviews img');
  await photoPicker().setInputFiles(file);await previews().waitFor();
  await field.fill('Фото из первого чата');
  release=await delayedSend(author,()=>author.page.locator('[data-ws-action="chat-send"]').click());
  await open(author,second);await photoPicker().setInputFiles(file);await previews().waitFor();
  await release();await author.page.waitForFunction(()=>hpointWorkspace.state.chatSending===false);
  assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.chatId),second);
  assert.equal(await field.inputValue(),'Черновик второго чата');
  assert.equal(await previews().count(),1);
  assert.equal(await author.page.locator('.workspaceMessages').getByText('Фото из первого чата',{exact:true}).count(),0);checks+=4;
  chat=(await get(author,'/api/chats?request_id='+first)).chats[0];
  const photoMessage=chat.messages.filter(m=>m.text==='Фото из первого чата');
  assert.equal(photoMessage.length,1);assert.equal(photoMessage[0].photos.length,1);checks+=2;
  await open(author,first);assert.equal(await field.inputValue(),'');assert.equal(await previews().count(),0);checks+=2;
  await open(author,second);assert.equal(await field.inputValue(),'Черновик второго чата');assert.equal(await previews().count(),1);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,textareaComposer:true,stableComposer:true,separateDrafts:true,sendRaceSafe:true,pendingTypingPreserved:true,photoSendRaceSafe:true,legitimateEmailPreserved:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
