'use strict';
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),errors=[],contexts=[];let checks=0;
 try{
  for(const width of [1440,390,320]){
   const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});contexts.push(context);
   await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/');await page.locator('[data-guest-enter]').waitFor();
   await page.locator('.guestHeaderActions [data-guest-auth="login"]').waitFor({state:'visible'});
   await page.locator('.guestHeaderActions [data-guest-auth="register"]').waitFor({state:'visible'});
   await page.locator('[data-guest-enter]').click();await page.locator('.hpointGuest .homeHero').waitFor();
   assert.equal(await page.locator('.guestHeaderActions [data-guest-auth="login"]').count(),1);
   assert.equal(await page.locator('.guestHeaderActions [data-guest-auth="register"]').count(),1);checks+=2;
   await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'guest-home-'+width+'.png'),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Guest page must not overflow');checks++;
   const boxes=await page.locator('.guestHeaderActions button').evaluateAll(nodes=>nodes.map(n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,fontSize:parseFloat(getComputedStyle(n).fontSize)}}));
   assert.ok(boxes[0].right<=boxes[1].left,'Header auth buttons must not overlap');checks++;
   assert.ok(boxes.every(b=>b.fontSize>=11&&b.right<=width),'Header auth labels must be readable');checks++;
   await page.locator('.homeHero [data-ws-action="request"]').click();await page.locator('#ae').waitFor();
   assert.match(await page.locator('.guestAuthReason').innerText(),/аккаунт/);checks++;
   await page.evaluate(()=>document.getElementById('modal').style.display='none');
   await page.locator('.homeHero [data-ws-action="queue"]').click();await page.locator('#ae').waitFor();checks++;
   await page.locator('#modalbody [data-guest-enter]').click();
   await page.locator('#sitePrimaryNav [data-guest-route="help"]').click();await page.locator('#guestHelpFilter').waitFor();
   assert.ok((await page.locator('#guestRequests .workspaceRequest').count())>=1);checks++;
   await page.locator('#guestCategory').selectOption('tech');
   assert.ok((await page.locator('#guestRequests').innerText()).includes('Техника'));checks++;
   await page.locator('[data-guest-request]').first().click();assert.match(await page.locator('#modalbody').innerText(),/Личные контакты/);checks++;
   await page.evaluate(()=>document.getElementById('modal').style.display='none');
   await page.locator('[data-guest-action="respond"]').first().click();await page.locator('#ae').waitFor();checks++;
   await page.evaluate(()=>document.getElementById('modal').style.display='none');
   await page.locator('#sitePrimaryNav [data-guest-route="activities"]').click();await page.locator('#guestServices').waitFor();
   await page.locator('#sitePrimaryNav [data-guest-route="work"]').click();await page.locator('.guestWorkOverview').waitFor();checks+=2;
   await page.reload();await page.locator('.guestWorkOverview').waitFor();checks++;
   await page.locator('.guestHeaderActions [data-guest-auth="register"]').click();await page.locator('#an').waitFor();
   assert.equal(await page.locator('#modalbody button').filter({hasText:/Telegram/}).count(),0);checks++;
   await page.evaluate(()=>document.getElementById('modal').style.display='none');
   await page.locator('.guestHeaderActions [data-guest-auth="login"]').click();await page.locator('#ae').fill('qa905@example.test');await page.locator('#ap').fill('SyntheticQa1');
   await page.locator('#modalbody button').filter({hasText:/^Войти$/}).click();
   await page.waitForFunction(()=>Boolean(window.hpointWorkspace?.state?.data?.user));
   assert.equal(await page.evaluate(()=>hpointGuest.active),false);assert.equal(await page.locator('body.hpointGuest').count(),0);checks+=2;
   await page.evaluate(()=>logout());await page.locator('.guestHeaderActions [data-guest-auth="login"]').waitFor();
   assert.equal(await page.evaluate(()=>Boolean(window.hpointWorkspace?.state?.data?.user)),false);checks++;
   await page.goto(base+'/#/help');await page.locator('#guestHelpFilter').waitFor();checks++;
   const payload=await(await context.request.get(base+'/api/guest')).json();assert.equal(payload.guest,true);
   for(const item of payload.requests)for(const key of ['email','phone','details','place','lat','lon','requester_id','photos'])assert.ok(!(key in item));checks++;
   for(const endpoint of ['/api/sync','/api/me','/api/helper/preferences','/api/chats','/api/commercial/dashboard']){
    const response=await context.request.get(base+endpoint);assert.ok([401,404].includes(response.status()),endpoint+' remains private');checks++;
   }
   const mutation=await context.request.post(base+'/api/requests/apply',{data:{request_id:payload.requests[0]?.id}});assert.equal(mutation.status(),401);checks++;
   if(width===1440){
    // Request 3 is the isolated harness's active agreement for user 901.
    await page.goto(base+'/?qa-chat-link=1#/help/chat/3');
    await page.locator('[data-guest-enter]').first().waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>location.hash),'#/help/chat/3');
    assert.equal(await page.locator('body.hpointGuest').count(),0);checks+=2;
    await page.locator('.guestHeaderActions [data-guest-auth="login"]').click();
    await page.locator('#ae').fill('qa901@example.test');await page.locator('#ap').fill('SyntheticQa1');
    await page.locator('#modalbody button').filter({hasText:/^Войти$/}).click();
    await page.waitForFunction(()=>window.hpointWorkspace?.state?.chat?.request_id===3);
    assert.equal(await page.locator('.workspaceChatPanel').count(),1);checks++;
   }
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors,desktopAndMobile:true,realPublicData:true,privateActionsRequireEmail:true}));
 }catch(error){console.error('Guest browser errors:',errors);throw error}finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
