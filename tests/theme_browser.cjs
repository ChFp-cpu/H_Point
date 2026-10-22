/* Run against a disposable local database only. Requires Playwright and Edge. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=process.env.HPOINT_QA_URL||'http://127.0.0.1:8110';
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base))throw Error('Only a local QA server is allowed');
const output=path.resolve(process.env.HPOINT_QA_OUTPUT||'.theme-qa');
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext();
  // Isolate visual QA from third-party SDK/network availability.
  await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  let checks=0;
  try{
    await page.goto(base+'/auth/telegram?ticket=theme-browser-data');
    await page.locator('#hpointWorkspace').waitFor();
    const routes=['#/home','#/help','#/rating','#/activities','#/league','#/donate','#/profile','#/profile/wallet','#/profile/billing','games'];
    const widths=[320,360,375,390,430,768,1024,1440,1920];
    const failures=[];
    for(const colorScheme of ['light','dark']){
      await page.emulateMedia({colorScheme});
      for(const width of widths){
        await page.setViewportSize({width,height:width<700?844:1000});
        for(const route of routes){
          await page.goto(base+'/'+route);
          if(route==='games')await page.locator('#games .game-card').first().waitFor();
          else if(['#/activities','#/league','#/donate'].includes(route))await page.locator('#workspaceCommunitySlot>.panel').waitFor();
          else await page.locator('.workspaceTitle').waitFor();
          const audit=await page.evaluate(()=>{
            const outside=[...document.querySelectorAll('body *')].filter(e=>{
              const s=getComputedStyle(e),r=e.getBoundingClientRect();
              if(s.display==='none'||s.visibility==='hidden'||!r.width||!r.height)return false;
              return r.left<-1||r.right>innerWidth+1;
            }).slice(0,8).map(e=>({tag:e.tagName,id:e.id,cls:String(e.className).slice(0,40)}));
            const controls=[...document.querySelectorAll('#sitePrimaryNav button,#sitePrimaryNav a,.workspaceHeaderActions button')].map(e=>e.getBoundingClientRect()).filter(r=>r.width&&r.height);
            const overlap=controls.some((a,i)=>controls.some((b,j)=>i<j&&a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1));
            return {outside,overlap,overflow:document.documentElement.scrollWidth>innerWidth+1,scheme:getComputedStyle(document.documentElement).colorScheme};
          });
          checks++;
          if(audit.outside.length||audit.overlap||audit.overflow||audit.scheme!==colorScheme)failures.push({width,route,colorScheme,...audit});
          if(width===1440||width===390)await page.screenshot({path:path.join(output,`${colorScheme}-${width}-${route.replace(/[^a-z]/g,'')}.png`),fullPage:true});
          if(route==='#/help'){
            assert.equal(await page.getByRole('heading',{name:'Smart Match',exact:true}).count(),1);
            assert.equal(await page.getByRole('heading',{name:'Чаты',exact:true}).count(),1);
          }
          if(route==='#/profile/billing')assert.equal(await page.locator('.workspaceProduct').count(),8);
        }
      }
      console.log('Responsive screens passed:',colorScheme);
    }
    fs.writeFileSync(path.join(output,'responsive.json'),JSON.stringify({checks,failures},null,2));
    assert.deepEqual(failures,[]);
    // Changing only the emulated system preference must preserve the exact DOM
    // input, draft, route and game session (no reload or rerender).
    await page.goto(base+'/#/profile');
    await page.getByRole('button',{name:'Редактировать профиль',exact:true}).click();
    await page.locator('#wsBio').fill('Черновик при смене системной темы');
    const draft=await page.locator('#wsBio').elementHandle();
    const routeBefore=page.url();
    for(const colorScheme of ['light','dark','light']){
      await page.emulateMedia({colorScheme});
      assert.equal(await page.locator('#wsBio').inputValue(),'Черновик при смене системной темы');
      assert.equal(await draft.evaluate(e=>e===document.querySelector('#wsBio')),true);
      assert.equal(page.url(),routeBefore);
    }
    for(const colorScheme of ['light','dark']){
      await page.emulateMedia({colorScheme});
      await page.screenshot({path:path.join(output,`${colorScheme}-profile-edit.png`),fullPage:true});
      await page.getByRole('button',{name:'+ Заявка',exact:true}).click();
      await page.locator('#qw').fill('Черновик заявки');
      await page.emulateMedia({colorScheme:colorScheme==='light'?'dark':'light'});
      assert.equal(await page.locator('#qw').inputValue(),'Черновик заявки');
      await page.locator('#modal .close').click();
    }
    await page.emulateMedia({colorScheme:'no-preference'});
    // Chromium may fall back to its host preference for this deprecated
    // emulation value. The application must follow what the browser reports.
    const nativePreference=await page.evaluate(()=>({dark:matchMedia('(prefers-color-scheme: dark)').matches,scheme:getComputedStyle(document.documentElement).colorScheme}));
    assert.equal(nativePreference.scheme,nativePreference.dark?'dark':'light');
    await page.goto(base+'/games');
    await page.locator('.game-card').filter({has:page.getByRole('heading',{name:'H-Safety',exact:true})}).getByRole('button',{name:'Играть',exact:true}).click();
    await page.locator('#gameRoot .scenario').waitFor();
    const gameBefore=await context.request.get(base+'/api/games/state').then(r=>r.json());
    const scenario=await page.locator('.scenario').elementHandle();
    await page.emulateMedia({colorScheme:'dark'});
    await page.emulateMedia({colorScheme:'light'});
    const gameAfter=await context.request.get(base+'/api/games/state').then(r=>r.json());
    assert.equal(gameAfter.active_session.id,gameBefore.active_session.id);
    assert.equal(await scenario.evaluate(e=>e===document.querySelector('.scenario')),true);
    await context.request.post(base+'/api/games/abandon',{data:{session_id:gameAfter.active_session.id}});
    for(const colorScheme of ['light','dark']){
      await page.emulateMedia({colorScheme});
      for(const width of [390,1440]){
        await page.setViewportSize({width,height:900});
        for(const game of ['H-Crossing','H-Dispatch','H-Match','H-Safety','H-Mission']){
          await page.goto(base+'/games');
          await page.locator('.game-card').filter({has:page.getByRole('heading',{name:game,exact:true})}).getByRole('button',{name:'Играть',exact:true}).click();
          await page.locator('#gameStage').waitFor();
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${game} ${width} ${colorScheme}`);
          if(game==='H-Crossing'){
            const car=await page.locator('.cross-car[data-car$=":0"]').first().elementHandle();
            const sample=()=>car.evaluate(e=>{const r=e.getBoundingClientRect(),y=e.dataset.y,c=document.querySelector(`.cross-cell[data-y="${y}"][data-x="0"]`),b=c.getBoundingClientRect();return{x:r.x,y:r.y,center:r.y+r.height/2,laneCenter:b.y+b.height/2,w:b.width,connected:e.isConnected}});
            const a=await sample();await page.waitForTimeout(170);const b=await sample();
            assert.equal(b.connected,true);assert.ok(Math.abs(b.center-b.laneCenter)<1,'Cars stay on their road');
            assert.ok(Math.abs(b.x-a.x)>1&&Math.abs(b.x-a.x)<a.w*.5,'Traffic moves continuously, not by teleportation');
            await page.getByRole('button',{name:'Вправо',exact:true}).click();
            await page.locator('.cross-player').locator('..').waitFor();
            await page.waitForFunction(()=>document.querySelector('.cross-player')?.parentElement.dataset.x==='4');
            assert.equal(await car.evaluate(e=>e.isConnected),true,'A move must not rebuild traffic');
            await page.locator('#pause').click();await page.locator('.pause-layer').waitFor();
            await page.waitForTimeout(40);const stopped=await sample();await page.waitForTimeout(170);
            assert.ok(Math.abs((await sample()).x-stopped.x)<1,'Pause freezes traffic');
            await page.locator('.pause-layer button').click();await page.locator('.pause-layer').waitFor({state:'hidden'});
          }
          checks++;
          await page.screenshot({path:path.join(output,`${colorScheme}-${width}-${game}.png`),fullPage:true});
          const snapshot=await context.request.get(base+'/api/games/state').then(r=>r.json());
          if(snapshot.active_session)assert.equal((await context.request.post(base+'/api/games/abandon',{data:{session_id:snapshot.active_session.id}})).ok(),true);
        }
      }
    }
    // Complete every turn-based game through the actual UI, not just screenshots.
    for(const game of ['H-Dispatch','H-Match','H-Safety','H-Mission']){
      await page.goto(base+'/games');
      await page.locator('.game-card').filter({has:page.getByRole('heading',{name:game,exact:true})}).getByRole('button',{name:'Играть',exact:true}).click();
      await page.locator('#gameStage').waitFor();
      for(let turn=0;turn<24;turn++){
        const snapshot=await context.request.get(base+'/api/games/state').then(r=>r.json()),session=snapshot.active_session;
        if(!session)break;
        const s=session.game_state;
        if(game==='H-Dispatch'){
          const job=s.jobs.find(item=>!item.assigned),worker=s.volunteers.find(v=>v.skills.includes(job.skill)&&Math.max(1,job.distance-Math.max(0,v.speed-2))<=job.deadline);
          assert.ok(worker,'Every dispatch task has an informed, feasible assignment');
          await page.locator(`[data-vol="${worker.id}"]`).click();
          await page.locator(`[data-job="${job.id}"]`).click();
        }else if(game==='H-Match'){
          const board=s.board,hasLine=b=>b.some((row,r)=>row.some((tile,c)=>(c<5&&tile===b[r][c+1]&&tile===b[r][c+2])||(r<5&&tile===b[r+1][c]&&tile===b[r+2][c])));
          let move;
          outer:for(let r=0;r<7;r++)for(let c=0;c<7;c++)for(const [dr,dc] of [[0,1],[1,0]]){const rr=r+dr,cc=c+dc;if(rr>6||cc>6)continue;const test=board.map(row=>row.slice());[test[r][c],test[rr][cc]]=[test[rr][cc],test[r][c]];if(hasLine(test)){move=[[r,c],[rr,cc]];break outer}}
          assert.ok(move,'Match board must retain a legal move');
          const before=await page.locator('.tile').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label')));
          await page.locator(`[data-r="${move[0][0]}"][data-c="${move[0][1]}"]`).click();
          assert.deepEqual(await page.locator('.tile').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label'))),before,'Selecting a tile must not shuffle the board');
          await page.locator(`[data-r="${move[1][0]}"][data-c="${move[1][1]}"]`).click();
        }else{
          await page.locator('[data-choice="0"]').click();
          await page.locator('#nextScenario').waitFor();
          const text=await page.locator('.feedback').textContent();await page.waitForTimeout(150);
          assert.equal(await page.locator('.feedback').textContent(),text,'Lessons advance only on an explicit click');
          await page.locator('#nextScenario').click();
        }
        await page.waitForTimeout(220);
      }
      await page.locator('.end-card').waitFor();
      assert.equal((await context.request.get(base+'/api/games/state').then(r=>r.json())).active_session,null,`${game} completes and saves its result`);
    }
    console.log('Gameplay passed: continuous traffic, pause, stable selection, four completed games');
    await page.goto(base+'/#/help');
    const chatButton=page.locator('.workspaceChatButton').first();
    await chatButton.waitFor();
    assert.equal(await chatButton.count(),1,'The fixture must exercise a real chat');
    {
      await chatButton.click();
      await page.locator('#wsChatText').waitFor();
      let sends=0;page.on('request',request=>{if(request.url().endsWith('/api/chats/send'))sends++});
      await page.locator('#wsChatText').fill('Проверка единственной отправки сообщения');
      await page.getByRole('button',{name:'Отправить',exact:true}).click();
      await page.getByText('Проверка единственной отправки сообщения',{exact:true}).first().waitFor();
      assert.equal(sends,1);assert.equal(await page.locator('#wsChatText').inputValue(),'');
    }
    // A small SDK double checks mounting, not third-party map rendering.
    // The same real map element and its controls must survive SPA navigation.
    await page.evaluate(()=>{
      window.ymaps={ready:callback=>callback(),Map:class{
        constructor(){this.geoObjects={add(){},remove(){}};this.container={fitToViewport(){}}}
        setCenter(){} setBounds(){}
      },Placemark:class{},util:{bounds:{fromPoints:points=>points}}};
    });
    await page.getByRole('button',{name:'Повторить загрузку карты',exact:true}).click();
    await page.locator('#workspaceMapSlot #mapTools').waitFor();
    await page.locator('#workspaceMapSlot #mapTasks .mapPrivacy').waitFor();
    const mapElement=await page.locator('#workspaceMapSlot #bigMap').elementHandle();
    await page.getByRole('button',{name:/^Профиль/}).first().click();
    await page.getByRole('button',{name:'Помощь',exact:true}).click();
    assert.equal(await mapElement.evaluate(e=>e===document.querySelector('#workspaceMapSlot #bigMap')),true);
    assert.equal(await page.locator('#workspaceMapSlot #mapTools').count(),1);
    assert.equal(await page.getByRole('button',{name:'◎ Показать меня',exact:true}).isVisible(),true);
    await page.goto(base+'/#/profile');
    await page.getByRole('button',{name:'Редактировать профиль',exact:true}).click();
    await page.locator('#wsName').fill('Проверенный профиль');await page.locator('#wsCity').fill('Новый город');
    await page.locator('#wsBio').fill('Профиль сохранён через интерфейс');await page.getByRole('button',{name:'Сохранить профиль',exact:true}).click();
    await page.getByRole('heading',{name:'Проверенный профиль',exact:true}).waitFor();
    const saved=await context.request.get(base+'/api/me').then(r=>r.json());assert.equal(saved.user.city,'Новый город');assert.equal(saved.user.bio,'Профиль сохранён через интерфейс');
    await page.getByRole('button',{name:'Панель администратора',exact:true}).click();await page.locator('.adminMetrics').waitFor();
    await page.locator('#modal .close').click();
    await page.getByRole('button',{name:'Сменить аккаунт',exact:true}).click();await page.getByRole('heading',{name:'Профили на этом устройстве',exact:true}).waitFor();
    await page.locator('#modal .close').click();
    await page.goto(base+'/#/activities');await page.getByRole('button',{name:'+ Создать событие',exact:true}).click();
    await page.locator('#eventTitle').fill('Проверочная встреча соседей');await page.locator('#eventPlace').fill('Тестовый общественный сад');
    const nextDay=new Date(Date.now()+86400000),localDate=new Date(nextDay.getTime()-nextDay.getTimezoneOffset()*60000).toISOString().slice(0,16);
    await page.locator('#eventStart').fill(localDate);await page.locator('#eventCapacity').fill('12');
    await page.getByRole('button',{name:'Опубликовать мероприятие',exact:true}).click();await page.getByRole('heading',{name:/Проверочная встреча соседей/}).waitFor();
    console.log('Core UI passed: chat, map lifecycle, profile save, admin, account menu, event creation');
    // Empty linked account and guest are checked independently.
    const empty=await browser.newContext({colorScheme:'light'}),emptyPage=await empty.newPage();
    await empty.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    await emptyPage.goto(base+'/auth/telegram?ticket=theme-browser-empty');
    for(const colorScheme of ['light','dark']){
      await emptyPage.emulateMedia({colorScheme});
      await emptyPage.setViewportSize({width:375,height:844});
      for(const route of routes){
        await emptyPage.goto(base+'/'+route);
        if(route==='games')await emptyPage.locator('.game-card').first().waitFor();
        else if(['#/activities','#/league','#/donate'].includes(route))await emptyPage.locator('#workspaceCommunitySlot>.panel').waitFor();
        else await emptyPage.locator('.workspaceTitle').waitFor();
        assert.equal(await emptyPage.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        checks++;
      }
    }
    const guest=await browser.newContext({viewport:{width:320,height:844}}),guestPage=await guest.newPage();
    await guest.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    for(const colorScheme of ['light','dark']){
      await guestPage.emulateMedia({colorScheme});await guestPage.goto(base);
      await guestPage.getByRole('button',{name:'Войти',exact:true}).first().waitFor();
      assert.equal(await guestPage.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await guestPage.screenshot({path:path.join(output,`${colorScheme}-guest-320.png`),fullPage:true});
      assert.equal(await guestPage.locator('.peopleCover img').getAttribute('src'),'/assets/community-volunteers.jpg');
      checks++;
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({ok:true,checks,liveThemePreservesDraft:true,liveThemePreservesGame:true,errors,output}));
  }catch(error){console.error('Browser errors:',errors);console.error(await page.locator('#workspaceMapSlot').textContent().catch(()=>''));await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
