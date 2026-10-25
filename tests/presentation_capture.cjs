const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const dir=path.join(process.env.HPOINT_QA_OUTPUT,'presentation');await fs.mkdir(dir,{recursive:true});
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:1440,height:920},colorScheme:'dark'});
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();await page.goto(base+'/auth/telegram?ticket='+ticket);
  await page.locator('#hpointWorkspace .workspaceTitle').waitFor();return{context,page};
 }
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper');
  await author.page.goto(base+'/#/help');await author.page.locator('.helpNavigation [data-tab="match"]').click();
  await author.page.locator('.workspaceCandidate [data-user="904"]').waitFor();
  await author.page.locator('#workspaceMatch').screenshot({path:path.join(dir,'matching.png')});
  await author.context.request.post(base+'/api/smart-match/assign',{data:{request_id:1,helper_id:904}});
  await helper.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.locator('.workspaceOfferNotice [data-accept="true"]').click();
  await helper.page.locator('#wsChatText').waitFor();
  await author.page.evaluate(()=>hpointWorkspace.refresh());
  await author.page.locator('#wsChatText').fill('Здравствуйте! Сможете помочь с настройкой техники сегодня после 18:00?');
  await author.page.locator('[data-ws-action="chat-send"]').click();
  await helper.page.evaluate(()=>hpointWorkspace.openChat(1));
  await helper.page.locator('#wsChatText').fill('Да, после 18:00 подойдёт. Давайте уточним детали здесь.');
  await helper.page.locator('[data-ws-action="chat-send"]').click();
  await author.page.evaluate(()=>hpointWorkspace.openChat(1));
  await author.page.locator('.workspaceMessages').getByText('Да, после 18:00 подойдёт.',{exact:false}).waitFor();
  await author.page.setViewportSize({width:1000,height:850});
  await author.page.locator('#toast').waitFor({state:'hidden'});
  await author.page.locator('.workspaceChatPanel').screenshot({path:path.join(dir,'chat.png')});
  await author.page.evaluate(()=>go('billing'));
  await author.page.locator('.workspaceProduct').first().waitFor();
  await author.page.screenshot({path:path.join(dir,'pricing.png'),fullPage:true});
  console.log(JSON.stringify({screenshots:dir,demoData:true}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
