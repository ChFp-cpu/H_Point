/* Photographs and participant lists on the disposable local email-only server. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {emailLogin}=require('./email_browser_login.cjs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await emailLogin(page,ticket);await page.locator('#hpointWorkspace').waitFor();
  await page.waitForFunction(()=>Boolean(window.HPointMedia));
  return {context,page};
 }
 const get=(actor,route)=>actor.context.request.get(base+route).then(async r=>{assert.equal(r.status(),200,await r.text());return r.json()});
 async function post(actor,route,data){let r=await actor.context.request.post(base+route,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper'),outsider=await login('theme-browser-empty');
  const photo=await author.page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=240;canvas.height=160;const c=canvas.getContext('2d');c.fillStyle='#b8f36b';c.fillRect(0,0,240,160);c.fillStyle='#172417';c.font='20px sans-serif';c.fillText('Synthetic photo',20,80);return canvas.toDataURL('image/png')});
  const file={name:'synthetic-photo.png',mimeType:'image/png',buffer:Buffer.from(photo.split(',')[1],'base64')};
  await author.page.locator('.workspaceHeaderActions [data-ws-action="request"]').click();
  await author.page.locator('#qw').fill('Собрать полку по фотографии');await author.page.locator('#qc').selectOption('tech');
  await author.page.locator('#requestNext').click();await author.page.locator('#qp').fill('Тестовый район');
  await author.page.locator('#requestNext').click();
  await author.page.locator('#requestPhotoPicker input').setInputFiles(file);
  await author.page.locator('#requestPhotoPicker .hpointPhotoPreviews img').waitFor();
  assert.equal(await author.page.locator('#requestPhotoPicker .hpointPhotoPreviews img').count(),1);checks++;
  await author.page.evaluate(()=>{window.hpointRequestPoint={lat:55.75,lon:37.62}});
  await author.page.locator('#createRequestButton').click();await author.page.locator('#modal').waitFor({state:'hidden'});
  const row=(await get(author,'/api/sync')).requests.find(request=>request.what==='Собрать полку по фотографии');
  assert.ok(row);assert.equal(row.photos.length,1);assert.equal('content_base64' in row.photos[0],false);checks+=3;
  const requestPhoto=await helper.context.request.get(base+row.photos[0].url);
  assert.equal(requestPhoto.status(),200);assert.match(requestPhoto.headers()['content-type'],/^image\/jpeg/);
  assert.ok((await requestPhoto.body()).subarray(0,2).equals(Buffer.from([0xff,0xd8])));checks+=3;
  await post(helper,'/api/requests/accept',{request_id:row.id});
  assert.equal((await outsider.context.request.get(base+row.photos[0].url)).status(),403);checks++;
  await helper.page.evaluate(id=>hpointWorkspace.openChat(id),row.id);
  await helper.page.locator('.workspaceChatForm .hpointPhotoPicker input').setInputFiles(file);
  await helper.page.locator('.workspaceChatForm .hpointPhotoPreviews img').waitFor();
  await helper.page.locator('#wsChatText').fill('');
  await helper.page.locator('[data-ws-action="chat-send"]').click();
  await helper.page.locator('.workspaceChatPanel .workspaceMessage .hpointPhotoGallery img').waitFor();
  const chat=(await get(author,'/api/chats?request_id='+row.id)).chats[0],message=chat.messages.at(-1);
  assert.equal(message.photos.length,1);assert.ok(!message.text||message.text==='Фото');checks+=2;
  assert.equal((await outsider.context.request.get(base+message.photos[0].url)).status(),403);checks++;
  await author.page.evaluate(id=>hpointWorkspace.openChat(id),row.id);
  await author.page.locator('.workspaceChatPanel .workspaceMessage .hpointPhotoGallery img').waitFor();checks++;
  for(const colorScheme of ['light','dark']){
   await author.page.emulateMedia({colorScheme});
   for(const width of [320,390,768,1440]){
    await author.page.setViewportSize({width,height:844});
    const fits=await author.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
    if(!fits){console.error('Photo layout overflow',width,colorScheme,await author.page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&e.getBoundingClientRect().width).slice(-15).map(e=>({tag:e.tagName,id:e.id,class:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))));await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'photo-layout-failure.png'),fullPage:true})}
    assert.equal(fits,true,'Photo chat fits '+width+' '+colorScheme);checks++;
   }
   await author.page.setViewportSize({width:390,height:844});await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'photo-chat-'+colorScheme+'.png'),fullPage:true});
  }
  const event=await post(author,'/api/events',{title:'Встреча с участниками',description:'Синтетическое мероприятие',place:'Тестовый парк',starts_at:new Date(Date.now()+86400000).toISOString(),capacity:8});
  await post(helper,'/api/events/join',{event_id:event.event_id});
  const participants=await get(author,'/api/events/participants?id='+event.event_id),helperName=(await get(helper,'/api/me')).user.name;
  assert.ok(participants.participants.some(person=>person.name===helperName));
  for(const person of participants.participants)assert.deepEqual(Object.keys(person).sort(),['name','profile_id']);checks+=2;
  await author.page.goto(base+'/#/activities');
  const card=author.page.locator('#eventsList .eventCard').filter({hasText:'Встреча с участниками'});
  await card.getByRole('button',{name:'Участники',exact:true}).click();
  await author.page.locator('.hpointParticipantList').waitFor();
  assert.match(await author.page.locator('.hpointParticipantList').innerText(),new RegExp(helperName));checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,requestPhoto:true,chatPhoto:true,privatePhotoAccess:true,eventParticipants:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
