/* Two-sided chat handoff after explicit consent, on disposable QA data. */
const {openHelpTab}=require('./help_navigation.cjs');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const contexts=[],errors=[];
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844}});contexts.push(context);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();
  return {context,page};
 }
 async function post(actor,route,data){const res=await actor.context.request.post(base+route,{data});assert.equal(res.status(),200,await res.text());return res.json()}
 async function match(actor){
  await actor.page.goto(base+'/#/help');
  await openHelpTab(actor.page,'match');
  await actor.page.waitForFunction(()=>hpointWorkspace.state.matchLoading===false);
 }
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  await post(author,'/api/smart-match/assign',{request_id:1,helper_id:904});
  await match(author);
  // The independent chat list may still describe the preceding sync snapshot.
  const staleChats=route=>route.fulfill({json:{ok:true,chats:[]}});
  await author.page.route(base+'/api/chats',staleChats);
  await helper.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await helper.page.locator('#wsChatText').waitFor();
  assert.equal(await helper.page.evaluate(()=>hpointWorkspace.state.chatId),1);
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.pendingChats.includes(1)),true);
  await author.page.unroute(base+'/api/chats',staleChats);
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  await author.page.locator('#wsChatText').waitFor();
  assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.chatId),1);
  assert.equal(await author.page.locator('#workspaceMatch').count(),0);
  await author.page.locator('#wsChatText').fill('Договоримся о времени');
  const sent=author.page.waitForResponse(response=>response.url().endsWith('/api/chats/send')&&response.request().method()==='POST');
  await author.page.locator('[data-ws-action="chat-send"]').click();
  assert.equal((await sent).status(),200);
  await helper.page.locator('.workspaceMessages').getByText('Договоримся о времени',{exact:false}).waitFor();
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.evaluate(()=>hpointWorkspace.refresh());
  assert.equal(await author.page.evaluate(()=>hpointWorkspace.state.helpTab),'chats');
  assert.equal(await helper.page.evaluate(()=>hpointWorkspace.state.helpTab),'chats');
  await author.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'chat-handoff-author.png'),fullPage:true});
  await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'chat-handoff-helper.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,chatHandoffBothSides:true,delayedChatSync:true,liveMessages:true}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
