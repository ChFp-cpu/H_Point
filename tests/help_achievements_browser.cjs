/* Games are paused; real help grants one shared, server-confirmed achievement. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local disposable QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
 async function login(ticket){
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});contexts.push(context);
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  await context.addInitScript(()=>Object.defineProperty(navigator,'geolocation',{configurable:true,value:{getCurrentPosition(ok){ok({coords:{latitude:55.75,longitude:37.61,accuracy:20}})}}}));
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base+'/auth/telegram?ticket='+ticket);await page.locator('#hpointWorkspace').waitFor();return {context,page};
 }
 async function get(actor,route){const response=await actor.context.request.get(base+route);assert.equal(response.status(),200,await response.text());return response.json()}
 async function post(actor,route,data){const response=await actor.context.request.post(base+route,{data});assert.equal(response.status(),200,await response.text());return response.json()}
 try{
  const author=await login('theme-browser-data'),helper=await login('mobile-helper'),legacy=await login('theme-browser-empty');
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){
   await helper.page.setViewportSize({width,height:844});await helper.page.emulateMedia({colorScheme});
   await helper.page.goto(base+'/#/home');await helper.page.locator('#sitePrimaryNav').waitFor();
   assert.equal(await helper.page.locator('#sitePrimaryNav a[href^="/games"]').count(),0);checks++;
   await helper.page.goto(base+'/#/profile');await helper.page.locator('.workspaceAchievements').waitFor();
   assert.equal(await helper.page.locator('a[href^="/games"]').count(),0);checks++;
   assert.equal(await helper.page.getByRole('heading',{name:'Достижения за помощь',exact:true}).count(),1);checks++;
   assert.equal(await helper.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;
  }
  const before=(await get(helper,'/api/sync')).user.balance;
  await author.page.evaluate(()=>go('requests'));
  const job=await post(author,'/api/requests',{what:'Проверка доброго дела',place:'Тест',time_needed:'Сегодня',urgency:'обычная',details:'Вымышленный сценарий',category:'tech'});
  await helper.page.setViewportSize({width:390,height:844});await helper.page.goto(base+'/#/help');await helper.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.locator('.helpNavigation [data-tab="open"]').click();
  await helper.page.locator('.workspaceRequest').filter({hasText:'#'+job.request_id+' ·'}).getByRole('button',{name:'Хочу помочь',exact:true}).click();
  await helper.page.locator('#wsChatText').waitFor();
  assert.equal(await helper.page.evaluate(()=>hpointWorkspace.state.chatId),job.request_id);checks++;
  await post(helper,'/api/requests/finish',{request_id:job.request_id});
  assert.equal((await get(helper,'/api/sync')).user.balance,before+20);checks++;
  await post(author,'/api/reviews',{request_id:job.request_id,side:'requester',rating:5});
  let state=await get(helper,'/api/sync');
  assert.equal(state.user.balance,before+30);assert.equal(state.help_achievements.unlocked_count,1);checks+=2;
  assert.equal(state.features.games,false);checks++;
  await helper.page.goto(base+'/#/profile');await helper.page.evaluate(()=>hpointWorkspace.refresh());
  await helper.page.locator('.workspaceAchievement').filter({hasText:'Первое доброе дело'}).filter({hasText:'начислено 10 HP'}).waitFor();checks++;
  for(const colorScheme of ['light','dark']){
   await helper.page.emulateMedia({colorScheme});
   await helper.page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'help-achievements-'+colorScheme+'.png'),fullPage:true});
  }
  await legacy.page.goto(base+'/#/profile');await legacy.page.evaluate(()=>hpointWorkspace.refresh());
  const historicalBefore=(await get(legacy,'/api/sync')).user.balance;
  await legacy.page.locator('[data-ws-action="help-achievements-claim"]').click();
  await legacy.page.waitForFunction(()=>hpointWorkspace.state.data.help_achievements.unlocked_count===1);
  assert.equal((await get(legacy,'/api/sync')).user.balance,historicalBefore+10);checks++;
  const repeated=await post(legacy,'/api/help-achievements/claim',{reward_hp:999999,user_id:904});
  assert.deepEqual(repeated.awarded,[]);assert.equal(repeated.balance,historicalBefore+10);checks+=2;
  const unchanged=(await get(helper,'/api/sync')).user.balance;
  for(const route of ['start','action','abandon','shop/purchase','shop/equip']){
   const response=await helper.context.request.post(base+'/api/games/'+route,{data:{game:'crossing',session_id:'old-session',action:{type:'finish'},item_id:'shield'}});
   assert.equal(response.status(),503);assert.equal((await response.json()).code,'games_paused');checks++;
  }
  assert.equal((await get(helper,'/api/sync')).user.balance,unchanged);checks++;
  const paused=await helper.page.goto(base+'/games');assert.equal(paused.status(),503);
  await helper.page.getByRole('heading',{name:'Игры пока на паузе'}).waitFor();
  assert.equal(await helper.page.locator('canvas').count(),0);checks+=2;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,gamesPaused:true,helpAwards:true,sharedBalance:true,errors}));
 }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
