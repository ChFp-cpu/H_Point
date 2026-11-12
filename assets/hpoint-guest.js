/* Visitor discovery uses the current H-Point workspace and real public data.
 * Authentication, private sync and all writes remain in the existing modules. */
(()=>{
 'use strict';
 const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const number=v=>new Intl.NumberFormat('ru-RU').format(Number(v)||0);
 const date=v=>{const d=new Date(v);return isNaN(d)?'Время уточняется':d.toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})};
 const previous={load:window.load,landing:window.landing,go:window.go,applySync:window.applySync,authForm:window.authForm};
 const store={get:k=>{try{return sessionStorage.getItem(k)}catch{return null}},set:(k,v)=>{try{sessionStorage.setItem(k,v)}catch{}},remove:k=>{try{sessionStorage.removeItem(k)}catch{}}};
 const publicRoutes=new Set(['home','help','activities','work','league']);
 const publicHash=()=> (location.hash.match(/^#\/(\w+)\/?$/)||[])[1];
 let active=false,wanted=publicRoutes.has(publicHash())||(!location.hash&&store.get('hpointGuestBrowse')==='1');
 let route='home',data=null,loading=null,category='',query='',resume=null;
 function ready(){document.documentElement.dataset.hpointBoot='ready';document.documentElement.setAttribute('aria-busy','false')}
 function leave(){active=false;wanted=false;data=null;document.body.classList.remove('hpointGuest');store.remove('hpointGuestBrowse')}
 function root(){return $('hpointWorkspace')}
 function header(){
  const primary=document.querySelector('.nav .sp'),actions=$('nav');
  if(primary)primary.innerHTML=active?'<nav id="sitePrimaryNav" style="--hp-nav-count:4" aria-label="Основная навигация">'+[['home','Главная'],['help','Помощь'],['work','Для работы'],['activities','Активности']].map(([key,title])=>'<button type="button" data-guest-route="'+key+'" class="'+(route===key?'active':'')+'"'+(route===key?' aria-current="page"':'')+'>'+title+'</button>').join('')+'</nav>':'';
  if(actions)actions.innerHTML='<div class="workspaceHeaderActions guestHeaderActions"><button class="btn light" type="button" data-guest-auth="login">Вход</button><button class="btn grad" type="button" data-guest-auth="register">Регистрация</button></div>';
  document.querySelector('.nav')?.classList.toggle('guestHeader',!active);
 }
 function landingButton(){
  const hero=document.querySelector('#landing .hero');if(!hero||hero.querySelector('[data-guest-enter]'))return;
  const actions=hero.querySelector('.actions')||hero.appendChild(Object.assign(document.createElement('div'),{className:'actions'}));
  actions.insertAdjacentHTML('beforeend','<button class="btn light guestEnter" type="button" data-guest-enter>Перейти на сайт <span aria-hidden="true">→</span></button>');
 }
 function auth(reg=false,reason='Для этого нужен аккаунт. Войдите или зарегистрируйтесь по email.',intent){
  resume=intent||(active?{route}:null);
  if(typeof window.authForm==='function')window.authForm(reg);
  const host=$('modalbody');if(host&&!host.querySelector('.guestAuthReason')){
   const notice=document.createElement('p');notice.className='guestAuthReason';notice.textContent=reason;
   (host.querySelector('h2')||host.firstElementChild)?.insertAdjacentElement('afterend',notice);
  }
 }
 window.authForm=function(register){
  const result=previous.authForm.apply(this,arguments);
  const form=$('modalbody');
  if(form&&!window.hpointWorkspace?.state?.data?.user){
   form.insertAdjacentHTML('beforeend','<button class="btn light guestEnter" type="button" data-guest-enter>Перейти на сайт</button>');
  }
  return result;
 };
 const action=(label,intent='',style='grad')=>'<button class="btn '+style+'" type="button" data-guest-action="'+esc(intent)+'">'+label+'</button>';
 function requestCard(item){return '<article class="workspaceRequest">'+window.HPointVisuals.requestVisual(item)+'<div class="workspaceRequestMain"><b>'+esc(item.what)+'</b><span class="workspaceRequestAuthor">Запрашивает: '+esc(item.requester_name||'Участник')+'</span><div class="workspaceRequestMeta">'+esc(item.category_name)+' · '+esc(item.time_needed||item.urgency||'Время по договорённости')+'</div><span class="workspaceTag">Открыта</span>'+(item.reward_rub?'<p class="muted">'+number(item.reward_rub)+' тест. ₽</p>':'<p class="muted">Без вознаграждения</p>')+'</div><div class="workspaceRequestActions"><button class="btn light" type="button" data-guest-request="'+item.id+'">Подробнее</button><button class="btn grad" type="button" data-guest-action="respond" data-id="'+item.id+'">Хочу помочь</button></div></article>'}
 function empty(text){return '<div class="workspaceEmpty">'+esc(text)+'</div>'}
 function services(){return data.services.length?'<div class="guestServiceGrid">'+data.services.map(item=>'<article class="workspaceCard guestService"><span class="workspaceKicker">'+esc(item.organization_title)+'</span><h3>'+esc(item.title)+'</h3><p class="muted">'+esc(item.description)+'</p><div class="guestServiceBottom"><b>'+number(item.price_rub)+' тест. ₽'+(item.duration_minutes?' · '+number(item.duration_minutes)+' мин':'')+'</b>'+action('Связаться','service','light')+'</div><a class="hpTextLink" href="'+esc(item.organization_url)+'">Страница организации →</a></article>').join('')+'</div>':empty('Опубликованных услуг пока нет. Здесь появятся предложения специалистов и организаций.')}
 function home(){const p=data.progress;return window.HPointVisuals.homeHero({})+'<section class="guestWelcome workspaceCard"><div><span class="workspaceKicker">МОЖНО ОСМОТРЕТЬСЯ</span><h2>Посмотрите, чем живёт H-Point</h2><p class="muted">Заявки, события и услуги открыты для просмотра. Чтобы договориться о помощи, войдите по email.</p></div>'+action('Создать аккаунт','register')+'</section>'+window.HPointVisuals.helpCategories()+'<section class="guestSection"><div class="hpSectionHeading"><h2>Сейчас нужна помощь</h2><button class="hpTextLink" type="button" data-guest-route="help">Все заявки →</button></div><div class="workspaceRequestList">'+(data.requests.slice(0,3).map(requestCard).join('')||empty('Открытых заявок сейчас нет.'))+'</div></section>'+window.HPointVisuals.workPromo()+'<section class="guestSection"><div class="hpSectionHeading"><h2>Услуги специалистов</h2><button class="hpTextLink" type="button" data-guest-route="activities" data-tab="services">Все услуги →</button></div>'+services()+'</section><section class="workspaceCard guestProgress"><div><span class="workspaceKicker">ЛИГА H-POINT</span><h2>Общий прогресс</h2></div><div><b>'+number(p.done)+'</b><span>завершённых дел</span></div><div><b>'+number(p.in_progress)+'</b><span>сейчас в работе</span></div><button class="hpTextLink" type="button" data-guest-route="league">Открыть Лигу →</button></section>'}
 function filteredRequests(){return data.requests.filter(item=>(!category||item.category===category)&&(!query||(item.what+' '+item.category_name).toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'))))}
 function help(){return window.HPointVisuals.helpHeader('open')+'<div class="workspaceSectionTabs"><button class="active" type="button" data-guest-route="help">Доступные заявки</button><button type="button" data-guest-action="my-requests">Мои заявки</button><button type="button" data-guest-action="match">Smart Match</button><button type="button" data-guest-action="chats">Чаты</button></div>'+window.HPointVisuals.helpCategories(true)+'<section class="workspaceCard guestFilter"><form id="guestHelpFilter"><label>Направление<select id="guestCategory" class="input"><option value="">Все направления</option>'+data.categories.map(item=>'<option value="'+esc(item.key)+'"'+(item.key===category?' selected':'')+'>'+esc(item.title)+'</option>').join('')+'</select></label><label>Поиск по заявкам<input id="guestQuery" class="input" name="query" type="search" autocomplete="off" placeholder="Что нужно сделать?" value="'+esc(query)+'"></label><button class="btn light" type="submit">Найти</button></form><div class="workspaceActions">'+action('Нужна помощь','request')+action('Настроить помощь','preferences','light')+'</div></section><div class="workspaceRequestList" id="guestRequests">'+(filteredRequests().map(requestCard).join('')||empty('Заявок по этим условиям пока нет. Попробуйте другое направление.'))+'</div>'}
 function activities(){return '<section class="communityPhotoStory"><div><span class="workspaceKicker">ЛЮДИ. ВСТРЕЧИ. ОБЩИЕ ДЕЛА.</span><h1 class="workspaceTitle">Есть повод собраться</h1><p>События рядом и услуги специалистов.</p><div class="workspaceActions">'+action('Создать мероприятие','event')+'</div></div>'+window.HPointVisuals.photo('events',{className:'hpCommunityPhoto'})+'</section><section class="guestSection"><h2>Ближайшие события</h2><div class="guestEventGrid">'+(data.events.map(item=>'<article class="workspaceCard guestEvent"><span class="workspaceKicker">'+esc(date(item.starts_at))+'</span><h3>'+esc(item.title)+'</h3><p class="muted">Организатор: '+esc(item.creator_name)+'</p><p>'+number(item.participant_count)+' участников'+(item.capacity?' · '+number(item.capacity)+' мест':'')+'</p>'+action('Участвовать','join-event')+'</article>').join('')||empty('Предстоящих мероприятий пока нет.'))+'</div></section><section class="guestSection" id="guestServices"><h2>Услуги специалистов</h2>'+services()+'</section>'}
 function work(){return '<section class="hpSectionHero"><div><span class="workspaceKicker">ДЛЯ РАБОТЫ</span><h1 class="workspaceTitle">Ваше дело — в одном кабинете</h1><p>Клиенты, расписание и инструменты под вашу профессию.</p><div class="workspaceActions">'+action('Создать рабочий кабинет','work')+'</div></div>'+window.HPointVisuals.photo('specialist',{className:'hpSectionHeroPhoto'})+'</section><section class="workspaceCard guestWorkOverview"><h2>Меньше рутины в ежедневных делах</h2><p class="muted">Ведите записи и задачи, работайте с клиентами и публикуйте услуги. Для разных профессий предусмотрены свои инструменты.</p><div class="guestWorkKinds"><div><b>Тренерам</b><span>Подопечные, занятия и показатели.</span></div><div><b>Прорабам</b><span>Объекты, задачи и сметы.</span></div><div><b>Специалистам и организациям</b><span>Услуги, записи и работа команды.</span></div></div></section><section class="guestSection"><h2>Опубликованные услуги</h2>'+services()+'</section>'}
 function league(){const p=data.progress;return '<section class="workspaceTopbar"><span class="workspaceKicker">ЛИГА H-POINT</span><h1 class="workspaceTitle">Каждое завершённое дело имеет значение</h1><p class="workspaceSubtitle">Общий прогресс сообщества по данным заявок.</p></section><section class="guestProgress workspaceCard"><div><b>'+number(p.total)+'</b><span>всего заявок</span></div><div><b>'+number(p.in_progress)+'</b><span>сейчас в работе</span></div><div><b>'+number(p.done)+'</b><span>дел завершено</span></div></section><section class="workspaceCard guestLeagueCategories"><h2>Направления помощи</h2>'+data.categories.map(item=>'<button class="guestLeagueRow" type="button" data-guest-category="'+esc(item.key)+'"><span>'+esc(item.title)+'</span><b>'+number(item.count)+'</b></button>').join('')+'</section>'}
 function render(){if(!active||!data)return;header();root().innerHTML=({home,help,activities,work,league}[route]||home)();root().dataset.guest='true';document.title='H-Point — '+({home:'помощь рядом',help:'помощь',activities:'активности',work:'для работы',league:'лига'}[route]||'помощь рядом')}
 function navigate(next,{keepScroll=false}={}){route=publicRoutes.has(next)?next:'home';if(location.hash!=='#/'+route)history.pushState(null,'','#/'+route);render();if(!keepScroll)window.scrollTo({top:0,behavior:'instant'})}
 async function snapshot(){const response=await fetch('/api/guest',{credentials:'same-origin',headers:{Accept:'application/json'},cache:'no-store'});if(!response.ok)throw new Error('Не удалось загрузить сайт');const result=await response.json();if(!result.ok)throw new Error(result.error||'Не удалось загрузить сайт');return result}
 async function enter(next='home'){
  wanted=true;active=true;store.set('hpointGuestBrowse','1');route=publicRoutes.has(next)?next:'home';
  document.body.classList.add('hpointGuest');$('landing').style.display='none';const app=$('app');app.style.display='block';app.classList.add('workspaceApp');
  if(!root()){const section=document.createElement('section');section.id='hpointWorkspace';section.setAttribute('aria-live','polite');app.prepend(section)}
  header();ready();if(data){navigate(route);return}
  root().innerHTML='<div class="workspaceEmpty" role="status">Загружаем заявки и события…</div>';
  try{loading=loading||snapshot().finally(()=>{loading=null});data=await loading;if(active)navigate(route)}catch{if(active)root().innerHTML='<section class="workspaceCard guestLoadError"><h1 class="workspaceTitle">Не удалось загрузить сайт</h1><p class="muted">Проверьте соединение и повторите попытку.</p><button class="btn grad" type="button" data-guest-retry>Повторить</button></section>'}
 }
 window.landing=function(){const result=previous.landing.apply(this,arguments);active=false;document.body.classList.remove('hpointGuest');landingButton();header();return result};
 window.applySync=function(payload){if(payload?.user)leave();return previous.applySync.apply(this,arguments)};
 window.load=async function(){
  await previous.load.apply(this,arguments);
  if(window.hpointWorkspace?.state?.data?.user){
   leave();
   if(!resume)return;
   const next=resume;resume=null;
   previous.go(({help:'requests',league:'progress'})[next.route]||next.route);
   if(next.action==='request')window.requestForm?.();
   if(next.action==='queue')window.helper?.();
  }else if(wanted){
   await enter(publicHash()||route);
  }
 };
 window.go=function(next){if(!active)return previous.go.apply(this,arguments);const mapped={requests:'help',events:'activities',services:'activities'}[next]||next;if(publicRoutes.has(mapped))return navigate(mapped);return auth(false,undefined,{route:mapped==='match'||mapped==='chats'?'help':route,action:next})};
 function requestDetails(id){const item=data.requests.find(row=>row.id===Number(id));if(!item)return;const modal=$('modal'),host=$('modalbody');host.innerHTML='<span class="workspaceKicker">'+esc(item.category_name)+'</span><h2>'+esc(item.what)+'</h2><p>Запрашивает: '+esc(item.requester_name)+'</p><p class="muted">'+esc(item.time_needed||item.urgency||'Время по договорённости')+'</p><p><b>'+(item.reward_rub?number(item.reward_rub)+' тест. ₽':'Без вознаграждения')+'</b></p><p class="muted">Личные контакты и адрес доступны только участникам договорённости.</p>'+action('Хочу помочь','respond');modal.style.display='flex'}
 document.addEventListener('click',event=>{
  const button=event.target.closest('button,a');if(!button)return;
  if(button.hasAttribute('data-guest-enter')){event.preventDefault();event.stopImmediatePropagation();window.closeModal?.();resume=null;enter('home');return}
  if(button.hasAttribute('data-guest-auth')){event.preventDefault();event.stopImmediatePropagation();auth(button.dataset.guestAuth==='register');return}
  if(!active)return;
  const controlled=button.closest('#hpointWorkspace,.nav')||button.hasAttribute('data-guest-action');if(!controlled)return;
  const stop=()=>{event.preventDefault();event.stopImmediatePropagation()};
  if(button.hasAttribute('data-guest-route')){stop();navigate(button.dataset.guestRoute);if(button.dataset.tab==='services')$('guestServices')?.scrollIntoView();return}
  if(button.hasAttribute('data-guest-category')){stop();category=button.dataset.guestCategory;navigate('help');return}
  if(button.hasAttribute('data-guest-action')){stop();const kind=button.dataset.guestAction;auth(kind==='register',undefined,{route:kind==='work'?'work':route,action:kind,request_id:Number(button.dataset.id)||null});return}
  if(button.hasAttribute('data-guest-request')){stop();requestDetails(button.dataset.guestRequest);return}
  if(button.hasAttribute('data-guest-retry')){stop();enter(route);return}
  if(button.dataset.wsAction){stop();const kind=button.dataset.wsAction;if(kind==='help-category'){category=button.dataset.category||'';navigate('help')}else if(kind==='help-tab'&&button.dataset.tab==='open')navigate('help');else if(kind==='help-filter-focus'){navigate('help');$('guestCategory')?.focus()}else if(kind==='route'&&publicRoutes.has(button.dataset.route))navigate(button.dataset.route);else auth(false,undefined,{route:kind==='request'?'help':route,action:kind});return}
  // Existing visual modules include inline workspace entry points. Prevent
  // them from opening a private dashboard while a visitor is browsing.
  const inline=button.getAttribute('onclick')||'';
  if(inline.includes('hpointCommercial.openCreation')){stop();auth(false,undefined,{route:'work',action:'work'});return}
  if(inline.includes('hpointCommercial.open')){stop();navigate('work');return}
  if(button.matches('.brandLogo')){stop();navigate('home')}
 },true);
 document.addEventListener('submit',event=>{if(!active||event.target.id!=='guestHelpFilter')return;event.preventDefault();event.stopImmediatePropagation();category=$('guestCategory').value;query=$('guestQuery').value.trim();render()},true);
 document.addEventListener('change',event=>{if(active&&event.target.id==='guestCategory'){category=event.target.value;render()}});
 window.addEventListener('hashchange',()=>{
  if(!active)return;
  const next=publicHash();
  if(publicRoutes.has(next)){route=next;render()}
  else{leave();window.landing()}
 });
 window.hpointGuest={enter,navigate,requireAuth:auth,get active(){return active}};
})();
