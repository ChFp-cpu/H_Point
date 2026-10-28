/* Category leagues, live earned progression and responsive, stable rendering. */
'use strict';
const {emailLogin}=require('./email_browser_login.cjs');
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local disposable QA only');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[];let checks=0;
  async function actor(ticket){const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});contexts.push(context);await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));if(ticket)await emailLogin(page,ticket);return {context,page}}
  async function get(a,url){const r=await a.context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json()}
  async function post(a,url,data){const r=await a.context.request.post(base+url,{data});assert.equal(r.status(),200,await r.text());return r.json()}
  async function category(page,key){await page.locator('#leagueCategoryFilter').selectOption(key);await page.waitForFunction(key=>document.getElementById('progressData')?.dataset.category===key,key)}
  try{
    const helper=await actor('mobile-helper'),author=await actor('theme-browser-data'),page=helper.page;
    await page.goto(base+'/#/league');await page.locator('.hpLeagueLevels').waitFor();
    assert.equal(await page.locator('.hpLeagueLevel').count(),6);assert.match(await page.locator('#leaguePersonalTitle').innerText(),/Новичок/);checks+=2;
    assert.equal(await page.locator('#leagueCategoryFilter option').count(),29);assert.equal(await page.locator('#leagueCategoryFilter optgroup').count(),5);checks+=2;
    await category(page,'pets');assert.match(await page.locator('#leagueBoardTitle').innerText(),/животных/);assert.equal(await page.locator('.duoChampionCard').count(),0);checks+=2;
    await page.locator('.hpLeagueAllDirections summary').click();assert.equal(await page.locator('.hpLeagueAllDirections [data-league-category]').count(),28);checks++;
    await page.locator('.hpLeagueAllDirections [data-league-category="design"]').click();await page.waitForFunction(()=>document.getElementById('progressData').dataset.category==='design');assert.equal(await page.locator('#leagueCategoryFilter').inputValue(),'design');checks++;
    await category(page,'pets');
    const created=await post(author,'/api/requests',{what:'Синтетический выгул питомца',place:'Тестовый район',time_needed:'По договорённости',urgency:'обычная',category:'pets',details:'Только вымышленные данные'}),id=created.request_id;
    const response=await post(helper,'/api/requests/apply',{request_id:id});
    const applications=(await get(author,'/api/sync')).applications,application=applications.find(item=>item.request_id===id&&item.helper_id===904);assert.ok(application);checks++;
    await post(author,'/api/requests/response/accept',{request_id:id,helper_id:904,application_token:application.application_token});
    await post(author,'/api/requests/finish',{request_id:id});await post(author,'/api/reviews',{request_id:id,side:'requester',rating:5});
    // A normal workspace refresh updates a filtered League without changing direction.
    await page.evaluate(()=>hpointWorkspace.refresh());
    await page.locator('#leaguePersonalTitle').filter({hasText:'Бронзовая'}).waitFor();
    assert.equal(await page.locator('#leagueCategoryFilter').inputValue(),'pets');assert.equal(await page.locator('.hpLeaguePersonal .hpLeagueProgressCaption b').innerText(),'1 дело');checks+=2;
    assert.equal(await page.locator('.hpLeagueLevel[aria-current="step"] b').innerText(),'Бронзовая');assert.equal(await page.locator('.duoChampionCard').count(),1);checks+=2;
    await page.locator('.duoChampion').first().click();await page.locator('.communityProfile').waitFor();assert.match(await page.locator('.communityProfile').innerText(),/Кандидат/);await page.evaluate(()=>closeModal());checks++;
    // Hide the review-once workflow so visual and stability checks exercise League.
    await page.evaluate(id=>{localStorage.setItem('hp-review-shown:904:'+id,'1');closeModal()},id);
    await category(page,'');assert.match(await page.locator('#leaguePersonalTitle').innerText(),/Бронзовая/);assert.equal(await page.locator('.duoChampionCard').count(),2);checks+=2;
    await page.evaluate(()=>{window.qaLeaguePersonal=document.querySelector('.hpLeaguePersonal');window.qaLeagueFilter=document.getElementById('leagueCategoryFilter');window.qaLeagueFilter.focus()});
    await page.evaluate(()=>hpointWorkspace.refresh());assert.equal(await page.locator('.hpLeaguePersonal').evaluate(node=>node===window.qaLeaguePersonal),true);assert.equal(await page.locator('#leagueCategoryFilter').evaluate(node=>node===window.qaLeagueFilter&&node===document.activeElement),true);checks+=2;
    // Late responses from one direction may not replace the next selection.
    const pets=await get(helper,'/api/progress?category=pets'),design=await get(helper,'/api/progress?category=design');let delayed=false;
    await page.route('**/api/progress?category=*',async route=>{const key=new URL(route.request().url()).searchParams.get('category');if(key==='pets'&&!delayed){delayed=true;await new Promise(resolve=>setTimeout(resolve,350));return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(pets)})}return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(key==='design'?design:pets)})});
    await page.locator('#leagueCategoryFilter').selectOption('pets');await page.locator('#leagueCategoryFilter').selectOption('design');await page.waitForFunction(()=>document.getElementById('progressData').dataset.category==='design');await page.waitForTimeout(450);assert.equal(await page.locator('#leagueCategoryFilter').inputValue(),'design');assert.match(await page.locator('#leaguePersonalTitle').innerText(),/Новичок/);assert.match(await page.locator('#leagueBoardTitle').innerText(),/Дизайн/);checks+=3;
    await page.unroute('**/api/progress?category=*');
    await category(page,'pets');
    for(const scheme of ['light','dark'])for(const width of [320,390,768,1440]){
      await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});
      const audit=await page.evaluate(()=>{
        const luminance=value=>{const channels=value.match(/[\d.]+/g).slice(0,3).map(Number).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4});return channels.reduce((total,value,index)=>total+value*[.2126,.7152,.0722][index],0)};
        const surfaces=[...document.querySelectorAll('.hpLeaguePersonal,.hpLeagueLevel,.hpLeaguePage .leagueBoard,.hpLeaguePage .leagueCategories,.hpLeaguePage .leagueStat,.hpLeaguePage .duoChampionCard')].map(node=>({cls:node.className,color:getComputedStyle(node).backgroundColor,light:luminance(getComputedStyle(node).backgroundColor)})).filter(item=>!item.color.endsWith(', 0)'));
        const outside=[...document.querySelectorAll('.hpLeaguePage *')].filter(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return r.width&&r.height&&s.visibility!=='hidden'&&(r.left<0||r.right>innerWidth+1)}).map(node=>node.className).slice(0,5);
        return{overflow:document.documentElement.scrollWidth>innerWidth+1,outside,surfaces};
      });
      assert.equal(audit.overflow,false,width+' '+scheme);assert.deepEqual(audit.outside,[],width+' '+scheme+' out of viewport');
      assert.deepEqual(audit.surfaces.filter(item=>scheme==='light'?item.light<.6:item.light>.4),[],width+' '+scheme+' stale surfaces');checks+=3;
      if([390,1440].includes(width))await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'help-league-'+scheme+'-'+width+'.png'),fullPage:true});
    }
    await page.route('**/api/progress?category=design',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'Synthetic unavailable'})}));
    await page.locator('#leagueCategoryFilter').selectOption('design');await page.locator('[data-league-retry]').waitFor();await page.unroute('**/api/progress?category=design');await page.locator('[data-league-retry]').click();await page.waitForFunction(()=>document.getElementById('progressData').dataset.category==='design');assert.match(await page.locator('#leagueBoardTitle').innerText(),/Дизайн/);checks++;
    // Real email registration creates negative IDs. Test podium AND ordinary rows.
    const emailHelpers=[];
    for(const index of [1,2]){
      const person=await actor(),name='Email помощник '+index,email='league'+index+'@example.test';
      await post(person,'/api/auth/register',{name,email,password:'SyntheticQa1',password_confirm:'SyntheticQa1'});
      const mail=JSON.parse(fs.readFileSync(process.env.HPOINT_QA_MAIL,'utf8'));assert.equal(mail.address,email);checks++;
      await post(person,'/api/auth/email/verify',{code:String(mail.code)});
      const uid=(await get(person,'/api/me')).user.id;assert.ok(uid<0);checks++;
      const request=(await post(author,'/api/requests',{what:'Синтетическая помощь email '+index,place:'Тестовый район',time_needed:'По договорённости',urgency:'обычная',category:'pets',details:'Только вымышленные данные'})).request_id;
      await post(person,'/api/requests/apply',{request_id:request});
      const application=(await get(author,'/api/sync')).applications.find(item=>item.request_id===request&&item.helper_id===uid);assert.ok(application);checks++;
      await post(author,'/api/requests/response/accept',{request_id:request,helper_id:uid,application_token:application.application_token});await post(author,'/api/requests/finish',{request_id:request});
      if(index===1)await post(author,'/api/reviews',{request_id:request,side:'requester',rating:5});
      emailHelpers.push({uid,name});
    }
    await category(page,'');
    for(const [index,person] of emailHelpers.entries()){
      const button=page.locator('[data-league-profile="'+person.uid+'"]');await button.waitFor();
      assert.equal(await button.evaluate(node=>node.classList.contains('duoChampion')),index===0);checks++;
      const profile=page.waitForResponse(response=>response.url()===base+'/api/community/profile?id='+person.uid);
      await button.click();assert.equal((await profile).status(),200);await page.locator('.communityProfile').waitFor();assert.match(await page.locator('.communityProfile h2').innerText(),new RegExp(person.name));await page.evaluate(()=>closeModal());checks+=2;
    }
    assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,earnedTiers:true,categoryRankings:true,liveRefresh:true,raceProtected:true,responsive:true,negativeEmailProfiles:true,errors}));
  }finally{for(const context of contexts)await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
