/* One response starts help and opens both chats; disposable local identities only. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();
  await page.evaluate(()=>Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(ok){ok({coords:{latitude:55.75,longitude:37.61,accuracy:20}})}}}));
  return {context,page};
 }
 const get=(actor,route)=>actor.context.request.get(base+route).then(r=>r.json());
 async function post(actor,route,data){let r=await actor.context.request.post(base+route,{data});assert.equal(r.status(),200,await r.text());return r.json()}
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  for(const colorScheme of ['light','dark']){
   for(const width of [320,390,768,1440]){
    for(const actor of [author,helper]){await actor.page.setViewportSize({width,height:844});await actor.page.emulateMedia({colorScheme})}
    const job=await post(author,'/api/requests',{what:'Мгновенная помощь '+colorScheme+' '+width,place:'Тестовый район',time_needed:'сегодня',urgency:'обычная',details:'Тест',category:'tech'});
    await author.page.evaluate(()=>hpointWorkspace.refresh());
    await helper.page.goto(base+'/#/help');await helper.page.evaluate(()=>hpointWorkspace.refresh());
    await helper.page.locator('.helpNavigation [data-tab="open"]').click();
    await helper.page.locator('.workspaceRequest').filter({hasText:'#'+job.request_id+' ·'}).getByRole('button',{name:'Хочу помочь',exact:true}).click();
    await helper.page.locator('#wsChatText').waitFor();
    assert.equal(await helper.page.evaluate(()=>hpointWorkspace.state.chatId),job.request_id);
    await author.page.evaluate(()=>hpointWorkspace.refresh());await author.page.locator('#wsChatText').waitFor();
    assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.chatId),job.request_id);checks+=2;
    const state=await get(author,'/api/sync');
    assert.equal(state.requests.find(row=>row.id===job.request_id).helper_id,904);
    assert.equal(state.requests.find(row=>row.id===job.request_id).status,'in_progress');
    assert.equal(state.applications.length,0);
    assert.equal((await get(helper,'/api/helper/offers')).offers.length,0);checks+=4;
    const repeat=await post(helper,'/api/requests/accept',{request_id:job.request_id});
    assert.equal(repeat.created,false);assert.equal(repeat.chat_ready,true);checks++;
    for(const actor of [author,helper]){assert.equal(await actor.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++}
    if(width===390)await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'instant-help-'+colorScheme+'.png'),fullPage:true});
    await helper.page.locator('#wsChatText').fill('Помощь принята одним нажатием');
    await helper.page.locator('[data-ws-action="chat-send"]').click();
    await helper.page.locator('.workspaceMessages').getByText('Помощь принята одним нажатием',{exact:false}).waitFor();
    await author.page.evaluate(id=>hpointWorkspace.openChat(id),job.request_id);
    await author.page.locator('.workspaceMessages').getByText('Помощь принята одним нажатием',{exact:false}).waitFor();checks++;
    await helper.page.goto(base+'/#/help/chat/'+job.request_id);await helper.page.locator('#wsChatText').waitFor();
    assert.equal(await helper.page.evaluate(()=>hpointWorkspace.state.chatId),job.request_id);checks++;
    const blocked=await helper.context.request.post(base+'/api/requests/finish',{data:{request_id:job.request_id}});
    assert.equal(blocked.status(),403);checks++;
    await author.page.goto(base+'/#/help');await author.page.evaluate(()=>hpointWorkspace.refresh());
    await author.page.locator('.helpNavigation [data-tab="mine"]').click();
    const finishButton=author.page.locator('[data-ws-action="finish"][data-id="'+job.request_id+'"]');
    await finishButton.waitFor();author.page.once('dialog',dialog=>dialog.dismiss());await finishButton.click();
    assert.equal((await get(author,'/api/sync')).requests.find(row=>row.id===job.request_id).status,'in_progress');checks++;
    author.page.once('dialog',dialog=>dialog.accept());await finishButton.click();
    await author.page.waitForFunction(id=>hpointWorkspace.state.data.requests.find(row=>row.id===id)?.status==='done',job.request_id);checks++;

   }
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,instantHelpBothSides:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
