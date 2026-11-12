/* Public two-direction onboarding; isolated local server and synthetic data. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.env.HPOINT_QA_URL;
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw Error('Local QA only');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),errors=[],writes=[];let checks=0;
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(new URL(request.url()).pathname)});
 const directions=scope=>page.locator(scope),work=scope=>directions(scope).getByRole('tab',{name:'Работа',exact:true}),help=scope=>directions(scope).getByRole('tab',{name:'Помощь',exact:true});
 async function verifyTabs(scope){
  const area=directions(scope);assert.equal(await area.getByRole('tablist').count(),1);assert.equal(await area.getByRole('tab').count(),2);checks+=2;
  await work(scope).click();assert.equal(await work(scope).getAttribute('aria-selected'),'true');assert.equal(await area.locator('[role=tabpanel]:visible').count(),1);assert.match(await area.locator('[role=tabpanel]:visible').innerText(),/Кабинет под вашу профессию/);checks+=3;
  await work(scope).press('ArrowLeft');assert.equal(await help(scope).getAttribute('aria-selected'),'true');assert.equal(await help(scope).evaluate(node=>node===document.activeElement),true);assert.match(await area.locator('[role=tabpanel]:visible').innerText(),/повседневные задачи/);checks+=3;
  await help(scope).press('End');assert.equal(await work(scope).getAttribute('aria-selected'),'true');assert.equal(await help(scope).getAttribute('tabindex'),'-1');checks+=2;
  await work(scope).press('Home');assert.equal(await help(scope).getAttribute('aria-selected'),'true');await help(scope).press('ArrowRight');assert.equal(await work(scope).getAttribute('aria-selected'),'true');checks+=2;
  for(const button of await area.getByRole('tab').all()){const box=await button.boundingBox();assert.ok(box.height>=44);checks++}
  assert.ok((await area.locator('[role=tabpanel]:visible').innerText()).length<400);checks++;
 }
 try{
  await page.goto(base);await page.locator('html[data-hpoint-boot=ready]').waitFor();await page.locator('.welcomeDirections .hpDirectionTab').first().waitFor();
  assert.equal(await work('.welcomeDirections').getAttribute('aria-selected'),'true');checks++;
  await verifyTabs('.welcomeDirections');
  await help('.welcomeDirections').click();await page.waitForTimeout(750);assert.equal(await help('.welcomeDirections').getAttribute('aria-selected'),'true');checks++;
  await page.evaluate(()=>authForm(true));await page.locator('.authDirections').waitFor();assert.equal(await work('.authDirections').getAttribute('aria-selected'),'true');checks++;
  await page.locator('#an').fill('Тестовый рабочий профиль');await page.locator('#ae').fill('onboarding@example.test');await page.locator('#ap').fill('SyntheticPass1');await page.locator('#ap2').fill('SyntheticPass1');
  await page.locator('#an').evaluate(node=>{window.qaNameNode=node;node.setSelectionRange(3,7)});const hint=await page.locator('#passwordHint').innerText();
  const expected={an:'Тестовый рабочий профиль',ae:'onboarding@example.test',ap:'SyntheticPass1',ap2:'SyntheticPass1'};
  for(const colorScheme of ['light','dark'])for(const width of [320,390,768,1440]){
   await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:width<700?844:1000});await verifyTabs('.authDirections');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('#an').evaluate(node=>node===window.qaNameNode),true);assert.deepEqual(await page.evaluate(()=>Object.fromEntries(['an','ae','ap','ap2'].map(id=>[id,document.getElementById(id).value]))),expected);assert.equal(await page.locator('#passwordHint').innerText(),hint);checks+=4;
   assert.equal(await page.locator('#modalbody input[type=email]').count(),1);assert.equal(await page.locator('#modalbody button').filter({hasText:/Telegram|Телеграм/}).count(),0);checks+=2;
   if(width===390)await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'registration-directions-'+colorScheme+'.png'),fullPage:true});
  }
  await page.locator('#an').focus();assert.deepEqual(await page.locator('#an').evaluate(node=>({start:node.selectionStart,end:node.selectionEnd})),{start:3,end:7});checks++;
  assert.deepEqual(writes,[]);checks++;
  // Exercise the existing registration/verification handlers after switching.
  await page.setViewportSize({width:390,height:844});await help('.authDirections').click();await page.getByRole('button',{name:'Зарегистрироваться',exact:true}).click();await page.locator('#emailCode').waitFor();
  const mail=JSON.parse(fs.readFileSync(process.env.HPOINT_QA_MAIL,'utf8'));assert.equal(mail.address,'onboarding@example.test');checks++;
  await page.locator('#emailCode').fill(String(mail.code));await page.getByRole('button',{name:'Подтвердить почту',exact:true}).click();await page.locator('#hpointWorkspace').waitFor();const response=await context.request.get(base+'/api/me');assert.equal(response.status(),200);assert.equal((await response.json()).user.email,'onboarding@example.test');checks+=2;
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({ok:true,checks,errors,workFirst:true,keyboardTabs:true,stableAuthFields:true,emailRegistration:true,responsive:true}));
 }catch(error){console.error('Registration UI:',await page.locator('#modalbody').innerText().catch(()=>''));await page.screenshot({path:path.join(process.env.HPOINT_QA_OUTPUT,'registration-directions-failure.png'),fullPage:true}).catch(()=>{});throw error}
 finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
