/* Long-conversation scrolling; disposable synthetic local accounts only. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),errors=[];let checks=0;
 const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
 const helper=await browser.newContext();
 for(const actor of [context,helper])await actor.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 async function get(actor,url){const response=await actor.request.get(base+url);assert.equal(response.status(),200,await response.text());return response.json()}
 async function post(actor,url,data){const response=await actor.request.post(base+url,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 const metrics=()=>page.locator('.workspaceMessages').evaluate(box=>({top:box.scrollTop,height:box.scrollHeight,client:box.clientHeight,gap:box.scrollHeight-box.clientHeight-box.scrollTop}));
 const settle=()=>page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.querySelectorAll('.workspaceMessages img')].map(img=>img.decode().catch(()=>{})));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))});
 async function refresh(){await page.evaluate(()=>hpointWorkspace.refresh());await settle()}
 async function bottom(label){await settle();const pos=await metrics();assert.ok(pos.height>pos.client+1000,'A long, genuinely scrollable conversation is required');assert.ok(pos.gap<=4,label+': '+JSON.stringify(pos));checks+=2}
 async function send(text,enter=true){await page.locator('#wsChatText').fill(text);const response=page.waitForResponse(r=>r.url()===base+'/api/chats/send'&&r.request().method()==='POST');if(enter)await page.locator('#wsChatText').press('Enter');else await page.locator('[data-ws-action="chat-send"]').click();assert.equal((await response).status(),200);await page.waitForFunction(()=>!hpointWorkspace.state.chatSending);await refresh()}
 try{
  await emailLogin(page,'theme-browser-data');
  await post(helper,'/api/auth/login',{email:'qa902@example.test',password:'SyntheticQa1'});
  const sync=await get(context,'/api/sync'),request=sync.requests.find(row=>row.status==='in_progress'&&Number(row.helper_id)===902);
  assert.ok(request,'Use the assigned synthetic help fixture');checks++;
  const chat=(await get(context,'/api/chats?request_id='+request.id)).chats[0];
  for(let i=0;i<65;i++)await post(context,'/api/chats/send',{request_id:request.id,chat_id:chat.id,text:'История '+String(i+1).padStart(2,'0')+'\nПодробности обсуждения тестовой помощи. Длинный разговор нужен для проверки настоящей прокрутки.'});
  await page.evaluate(({rid,cid})=>hpointWorkspace.openChat(rid,cid),{rid:request.id,cid:chat.id});
  await page.locator('#wsChatText').waitFor();await page.bringToFront();await bottom('Opening shows the newest messages');
  await refresh();await bottom('Initial list refresh preserves the end');
  await send('Новое сообщение через Enter');await bottom('Own Enter send and full sync stay at the end');
  await send('Новое сообщение кнопкой',false);await bottom('Own button send and full sync stay at the end');
  // Incoming messages leave the reader at the end if that is where they were.
  await post(helper,'/api/chats/send',{request_id:request.id,chat_id:chat.id,text:'Ответ помощника в конце разговора'});
  await page.locator('.workspaceMessages').getByText('Ответ помощника в конце разговора').waitFor();await bottom('Incoming message follows the end');await refresh();await bottom('Incoming list refresh stays at the end');
  // Reading history must survive both the one-second message poll and the
  // subsequent full workspace sync without destroying focus or the draft.
  const field=page.locator('#wsChatText');await field.fill('Несохранённый черновик');await field.evaluate(node=>{window.qaScrollComposer=node;node.focus();node.setSelectionRange(3,9)});
  await page.locator('.workspaceMessages').evaluate(box=>box.scrollTop=320);
  const history=(await metrics()).top;
  await post(helper,'/api/chats/send',{request_id:request.id,chat_id:chat.id,text:'Входящее во время чтения истории'});
  await page.locator('.workspaceMessages').getByText('Входящее во время чтения истории').waitFor();
  assert.ok(Math.abs((await metrics()).top-history)<=4,'Polling preserves the historical reading position');checks++;
  await refresh();assert.ok(Math.abs((await metrics()).top-history)<=4,'Full sync preserves the historical reading position');checks++;
  assert.equal(await field.inputValue(),'Несохранённый черновик');assert.equal(await field.evaluate(node=>node===window.qaScrollComposer),true);assert.deepEqual(await field.evaluate(node=>({focused:document.activeElement===node,start:node.selectionStart,end:node.selectionEnd})),{focused:true,start:3,end:9});checks+=3;
  // Sending intentionally returns to the latest message even from history.
  await send('Отправка из истории возвращает к последнему сообщению');await bottom('Own send from history follows the newest message');
  const photo=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=240;canvas.height=360;const g=canvas.getContext('2d');g.fillStyle='#628971';g.fillRect(0,0,240,360);return canvas.toDataURL('image/png')});
  await page.locator('.workspaceChatForm .hpointPhotoPicker input').setInputFiles({name:'scroll-portrait.png',mimeType:'image/png',buffer:Buffer.from(photo.split(',')[1],'base64')});
  await page.locator('.workspaceChatForm .hpointPhotoPreviews img').waitFor();
  await send('Фотография в конце переписки');await page.locator('.workspaceMessages .hpointPhotoGallery img').last().waitFor();await bottom('Photo gallery layout and full sync stay at the end');
  // Let a periodic full sync run after the optimistic/local send path.
  await page.waitForTimeout(8500);await bottom('Periodic refresh does not jump to the first message');
  assert.equal((await get(context,'/api/chats?chat_id='+chat.id)).chats[0].messages.filter(row=>row.text==='Фотография в конце переписки').length,1);checks++;
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'chat-scroll-mobile.png'),fullPage:true});
  console.log(JSON.stringify({ok:true,checks,errors,initialLatest:true,ownSendLatest:true,photoLatest:true,historyReadingPreserved:true,focusAndDraftPreserved:true,fullRefreshStable:true}));
 }finally{await context.close();await helper.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
