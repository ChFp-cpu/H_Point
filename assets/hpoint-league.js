/* Earned leagues and category rankings share the request category catalogue. */
(()=>{
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const number=value=>Math.max(0,Math.trunc(Number(value)||0));
  // Email-only profiles have negative IDs. Counts and identities are distinct.
  const userId=value=>Number.isSafeInteger(Number(value))?Number(value):0;
  const count=value=>number(value).toLocaleString('ru-RU');
  const plural=(value,forms)=>{const n=number(value),tail=n%100;return forms[tail>=11&&tail<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2]};
  const deeds=value=>count(value)+' '+plural(value,['дело','дела','дел']);
  const catalog=()=>window.hpointHelpCategories?.catalog||[];
  const groups=()=>window.hpointHelpCategories?.groups||[];
  const owner=()=>String(window.hpointWorkspace?.state?.data?.current_user_id??'');
  const state={owner:null,category:'',data:null,signature:'',globalSignature:'',request:0,pending:null,refreshAfter:false};
  const active=()=>window.hpointWorkspace?.state?.route==='league'||/^#\/league(?:\/|$)/.test(location.hash);
  const byId=id=>document.getElementById(id);
  function account(){
    const id=owner();if(state.owner===id)return;
    state.owner=id;state.category='';state.data=null;state.signature='';state.globalSignature='';state.pending=null;state.refreshAfter=false;state.request++;
    const select=byId('leagueCategoryFilter');if(select)select.value='';
    const host=byId('progressData');if(host)host.replaceChildren();
  }
  function options(){
    let html='<option value="">Все направления</option>';
    for(const group of groups()){
      const rows=catalog().filter(item=>item.group===group.key);
      if(rows.length)html+='<optgroup label="'+esc(group.title)+'">'+rows.map(item=>'<option value="'+esc(item.key)+'">'+esc(item.title||item.label)+'</option>').join('')+'</optgroup>';
    }
    const grouped=new Set(groups().map(group=>group.key));
    html+=catalog().filter(item=>!grouped.has(item.group)).map(item=>'<option value="'+esc(item.key)+'">'+esc(item.title||item.label)+'</option>').join('');
    return html;
  }
  function ensurePanel(){
    let panel=byId('p-progress');
    if(!panel){const app=byId('app');if(!app)return null;panel=document.createElement('section');panel.id='p-progress';app.appendChild(panel)}
    if(!panel.classList.contains('hpLeaguePage')){
      panel.className='panel showcasePanel hpLeaguePage';
      panel.innerHTML='<div class="leagueHeading"><span class="leagueHeadingMark" aria-hidden="true">✦</span><div><h2>Лига H-Point</h2><p>Реальная помощь. Свой уровень в каждом направлении.</p></div></div><div class="hpLeagueToolbar"><label for="leagueCategoryFilter">Направление<select id="leagueCategoryFilter" class="input">'+options()+'</select></label><button class="btn light" id="leagueRefresh" type="button">Обновить</button></div><p id="leagueStatus" class="hpLeagueStatus" role="status" aria-live="polite"></p><div id="progressData"></div>';
      panel.addEventListener('change',event=>{
        if(event.target.id!=='leagueCategoryFilter')return;
        state.category=event.target.value;state.data=null;state.signature='';loadProgress();
      });
      panel.addEventListener('click',event=>{
        const button=event.target.closest?.('button');if(!button)return;
        if(button.id==='leagueRefresh'||button.hasAttribute('data-league-retry')){loadProgress();return}
        if(button.hasAttribute('data-league-profile'))window.openCommunityProfile?.(userId(button.dataset.leagueProfile));
        if(button.hasAttribute('data-league-category')){
          state.category=button.dataset.leagueCategory;state.data=null;state.signature='';byId('leagueCategoryFilter').value=state.category;
          loadProgress();byId('leagueCategoryFilter').focus({preventScroll:true});
        }
        if(button.hasAttribute('data-league-help'))window.go?.('requests');
      });
    }
    account();const select=byId('leagueCategoryFilter');if(select)select.value=state.category;
    return panel;
  }
  function tierName(person){return person?.league?.title||'Новичок'}
  function rating(person){return person.rating==null?'Без оценок':'★ '+Number(person.rating).toFixed(1)}
  function personCard(person){
    const mine=String(person.user_id)===state.owner;
    return '<button type="button" class="duoChampion'+(number(person.position)===1?' first':'')+'" data-league-profile="'+userId(person.user_id)+'" aria-label="Отзывы: '+esc(person.name)+'"><span class="duoChampionCard'+(mine?' hpLeagueMine':'')+'"><span class="duoRankBadge">'+count(person.position)+'</span><span class="duoAvatar" aria-hidden="true">'+esc((person.name||'?').slice(0,1).toLocaleUpperCase())+'</span><span class="hpLeaguePersonCopy"><span class="duoChampionName">'+esc(person.name)+(mine?' · вы':'')+'</span><span class="duoChampionMeta">'+deeds(person.helped)+' · '+rating(person)+'</span></span><span class="duoChampionScore">'+esc(tierName(person))+'</span></span></button>';
  }
  function personRow(person){
    const mine=String(person.user_id)===state.owner;
    return '<button type="button" class="leagueRow'+(mine?' hpLeagueMine':'')+'" data-league-profile="'+userId(person.user_id)+'"><span class="leaguePosition">'+count(person.position)+'</span><span class="leagueAvatar" aria-hidden="true">'+esc((person.name||'?').slice(0,1).toLocaleUpperCase())+'</span><span class="hpLeaguePersonCopy"><span class="leagueMemberName">'+esc(person.name)+(mine?' · вы':'')+'</span><span class="leagueMemberMeta">'+deeds(person.helped)+' · '+esc(tierName(person))+'</span></span><span class="leagueRating">'+rating(person)+'</span></button>';
  }
  function personal(data){
    const person=data.current_user;if(!person)return '';
    const league=person.league||{},progress=Math.min(100,number(league.progress_percent));
    const message=league.next_at==null?'Высшая лига достигнута. Спасибо за ваш вклад!':'Следующая — '+esc(league.next_title||'новая лига')+'. Осталось '+deeds(league.remaining)+'.';
    return '<section class="hpLeaguePersonal" aria-labelledby="leaguePersonalTitle"><div><span class="hpLeagueEyebrow">Ваш уровень'+(state.category?' в направлении':'')+'</span><h3 id="leaguePersonalTitle">'+esc(tierName(person))+(league.key&&league.key!=='newcomer'?' лига':'')+'</h3><p>'+message+'</p></div><div class="hpLeaguePersonalProgress"><span class="hpLeagueProgressCaption"><b>'+deeds(person.helped)+'</b><span>'+(person.position?'Место '+count(person.position):'Первое дело откроет рейтинг')+'</span></span><div class="leagueProgressTrack" role="progressbar" aria-label="Прогресс до следующей лиги" aria-valuemin="0" aria-valuemax="100" aria-valuenow="'+progress+'"><i style="--league-progress:'+progress+'%"></i></div><small>Завершение подтверждает автор заявки.</small></div></section>';
  }
  function tiers(data){
    const current=data.current_user?.league?.key;
    return '<section class="hpLeagueLevels" aria-label="Лиги по числу завершённых дел">'+(data.leagues||[]).map(tier=>'<div class="hpLeagueLevel'+(tier.key===current?' isCurrent':'')+'"'+(tier.key===current?' aria-current="step"':'')+'><b>'+esc(tier.title)+'</b><span>'+(tier.key==='newcomer'?'Старт':count(tier.min_completed)+(tier.next_at==null?'+':'–'+count(number(tier.next_at)-1))+' '+plural(tier.min_completed===1?2:tier.min_completed,['дело','дела','дел']))+'</span></div>').join('')+'</section>';
  }
  function directions(data){
    const rows=data.categories||[],byKey=new Map(rows.map(item=>[item.key,item]));
    const activeRows=rows.filter(item=>number(item.active)>0).sort((a,b)=>number(b.active)-number(a.active)||number(b.count)-number(a.count)).slice(0,5);
    const categoryRow=(row)=>'<button type="button" class="hpLeagueDirection'+(row.key===state.category?' isSelected':'')+'" data-league-category="'+esc(row.key)+'"><span>'+esc(row.title)+'</span><small>'+count(row.active)+' активн. · '+count(row.done)+' заверш.</small></button>';
    return '<aside class="leagueCategories"><div class="leagueSectionHead"><div><h3>Направления помощи</h3><p>Рейтинг и уровень отдельно в каждой сфере.</p></div></div>'+(activeRows.length?'<div class="hpLeagueActiveDirections"><b class="hpLeagueSmallTitle">Сейчас нужна помощь</b>'+activeRows.map(categoryRow).join('')+'</div>':'')+'<details class="hpLeagueAllDirections"><summary>Все направления · '+count(rows.length)+'</summary>'+groups().map(group=>{
      const items=catalog().filter(item=>item.group===group.key).map(item=>byKey.get(item.key)).filter(Boolean);
      return items.length?'<section><h4>'+esc(group.title)+'</h4>'+items.map(categoryRow).join('')+'</section>':'';
    }).join('')+'</details></aside>';
  }
  function paint(data){
    const host=byId('progressData');if(!host)return;
    const signature=JSON.stringify(data);if(signature===state.signature&&host.dataset.category===state.category)return;
    state.signature=signature;state.data=data;
    const opened=new Set([...host.querySelectorAll('details[open]')].map(node=>node.className));
    const focus=document.activeElement,focusId=focus&&host.contains(focus)?focus.dataset.leagueProfile||focus.dataset.leagueCategory:null;
    const summary=data.summary||{},leaders=data.leaderboard||[];
    host.innerHTML=personal(data)+tiers(data)+'<section class="hpLeagueCounts" aria-label="Статистика выбранного направления"><article class="leagueStat"><b>'+count(summary.total)+'</b><span>всего заявок</span></article><article class="leagueStat"><b>'+count(summary.active)+'</b><span>активных</span></article><article class="leagueStat"><b>'+count(summary.done)+'</b><span>дел завершено</span></article></section><div class="hpLeagueLayout"><section class="leagueBoard" aria-labelledby="leagueBoardTitle"><div class="leagueSectionHead"><div><h3 id="leagueBoardTitle">'+esc(state.category?(data.category_title||'Рейтинг направления'):'Таблица лидеров')+'</h3><p>Завершённые дела, затем оценки участников.</p></div><span class="leaguePill">Топ '+count(leaders.length)+'</span></div>'+(leaders.length?'<div class="duoPodium">'+leaders.slice(0,3).map(personCard).join('')+'</div>'+(leaders.length>3?'<div class="leagueRows">'+leaders.slice(3).map(personRow).join('')+'</div>':''):'<div class="leagueEmpty"><b>Здесь можно стать первым</b><p>После завершённой помощи появятся участники и места.</p><button type="button" class="btn light" data-league-help>Перейти к заявкам</button></div>')+(data.current_user?.position>20?'<div class="hpLeagueOutsideRank">'+personRow(data.current_user)+'</div>':'')+'<details class="hpLeagueRules"><summary>Как устроена Лига</summary><p>Уровень зависит от числа завершённых дел за всё время. В выбранном направлении учитывается помощь только в этой сфере. При равном числе дел выше средняя оценка; при равенстве — стабильный порядок участников.</p><p>Подписки, покупки и баланс HP не меняют уровень и место. Отменённые и незавершённые заявки не учитываются.</p></details></section>'+directions(data)+'</div>';
    host.dataset.category=state.category;
    for(const node of host.querySelectorAll('details'))if(opened.has(node.className))node.open=true;
    if(focusId)for(const node of host.querySelectorAll('button'))if((node.dataset.leagueProfile||node.dataset.leagueCategory)===focusId){node.focus({preventScroll:true});break}
  }
  function busy(value){
    const panel=byId('p-progress');if(panel)panel.setAttribute('aria-busy',String(value));
    const refresh=byId('leagueRefresh');if(refresh)refresh.disabled=value;
    const status=byId('leagueStatus');if(status)status.textContent=value?'Обновляем…':'';
  }
  async function loadProgress(){
    if(!ensurePanel())return;
    const category=state.category,user=state.owner;
    if(state.pending?.category===category&&state.pending.owner===user)return state.pending.promise;
    const request=++state.request,host=byId('progressData');
    if(!state.data)host.innerHTML='<div class="leagueEmpty" role="status">Загружаем Лигу…</div>';
    busy(true);
    const promise=(async()=>{
      try{
        const data=await window.api('/api/progress'+(category?'?category='+encodeURIComponent(category):''));
        if(request!==state.request||user!==owner()||category!==state.category)return;
        paint(data);
      }catch(error){
        if(request!==state.request||user!==owner()||category!==state.category)return;
        if(!state.data)host.innerHTML='<div class="leagueEmpty"><b>Лига временно недоступна</b><p>Попробуйте обновить через несколько секунд.</p><button type="button" class="btn light" data-league-retry>Повторить</button></div>';
        const status=byId('leagueStatus');if(status)status.textContent='Не удалось обновить Лигу. Показаны последние данные.';
      }finally{
        if(request===state.request){const message=byId('leagueStatus')?.textContent;busy(false);if(message&&message!=='Обновляем…')byId('leagueStatus').textContent=message;state.pending=null;if(state.refreshAfter){state.refreshAfter=false;loadProgress()}}
      }
    })();
    state.pending={category,owner:user,promise};return promise;
  }
  function update(data){
    account();const signature=JSON.stringify(data);if(signature===state.globalSignature)return;
    state.globalSignature=signature;if(!active()||!byId('progressData'))return;
    if(state.category){if(state.pending)state.refreshAfter=true;else loadProgress();return}
    // The workspace's newer snapshot supersedes an older in-flight refresh.
    if(state.pending){state.request++;state.pending=null;busy(false)}
    paint(data);
  }
  const style=document.createElement('style');style.id='hpointLeagueStyle';style.textContent=`
  .hpLeaguePage{max-width:none;margin:0;min-width:0}.hpLeaguePage *{box-sizing:border-box}.hpLeaguePage .leagueHeading{margin-bottom:22px}.hpLeaguePage .leagueHeading h2{font-size:clamp(26px,3.5vw,36px);letter-spacing:-.04em}.hpLeaguePage .leagueHeading p{font-size:13px;line-height:1.6}.hpLeaguePage .leagueHeadingMark{flex-basis:44px;width:44px;height:44px;font-size:24px;border-radius:14px}.hpLeagueToolbar{display:flex;gap:12px;align-items:end;justify-content:space-between}.hpLeagueToolbar label{display:grid;gap:7px;flex:1;max-width:480px;min-width:0;color:var(--hp-text-secondary);font-size:12px;font-weight:700}.hpLeagueToolbar .input{width:100%;font-size:14px;min-height:44px}.hpLeagueToolbar .btn{min-height:44px}.hpLeagueStatus{height:20px;margin:6px 0;color:var(--hp-text-secondary);font-size:12px;line-height:1.4}.hpLeaguePersonal{display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:28px;padding:24px;border:1px solid var(--hp-border);border-radius:20px;background:linear-gradient(120deg,var(--hp-hover),var(--hp-surface));color:var(--hp-text-primary)}.hpLeagueEyebrow{display:block;font-size:11px;letter-spacing:.04em;font-weight:800;color:var(--hp-accent-text)}.hpLeaguePersonal h3{margin:7px 0;font-size:27px;font-weight:800;letter-spacing:-.035em;color:var(--hp-text-primary)}.hpLeaguePersonal p{margin:6px 0 0;font-size:13px;line-height:1.65;color:var(--hp-text-secondary)}.hpLeagueProgressCaption{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;align-items:center;font-size:12px;color:var(--hp-text-secondary);margin-bottom:9px}.hpLeagueProgressCaption b{font-size:15px;color:var(--hp-text-primary)}.hpLeaguePage .leagueProgressTrack{height:9px;border:0;box-shadow:none}.hpLeaguePage .leagueProgressTrack i{animation:none;box-shadow:none;background:var(--hp-accent-text)}.hpLeaguePersonalProgress small{display:block;margin-top:8px;font-size:11px;line-height:1.55;color:var(--hp-text-secondary)}.hpLeagueLevels{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;margin:10px 0 20px}.hpLeagueLevel{min-width:0;padding:11px 9px;border:1px solid var(--hp-border);border-radius:12px;background:var(--hp-surface);color:var(--hp-text-secondary)}.hpLeagueLevel.isCurrent{background:var(--hp-hover);border-color:var(--hp-accent-text)}.hpLeagueLevel b,.hpLeagueLevel span{display:block;overflow-wrap:anywhere}.hpLeagueLevel b{font-size:12px;color:var(--hp-text-primary);line-height:1.5}.hpLeagueLevel span{font-size:10px;margin-top:4px}.hpLeagueCounts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:20px}.hpLeaguePage .leagueStat{padding:16px!important;min-height:0;border-width:1px;box-shadow:none;border-radius:15px}.hpLeaguePage .leagueStat b{font-size:25px;line-height:1.2}.hpLeaguePage .leagueStat span{font-size:11px;line-height:1.5}.hpLeagueLayout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(260px,1fr);gap:16px;align-items:start}.hpLeaguePage .leagueBoard,.hpLeaguePage .leagueCategories{padding:20px;border-width:1px;border-radius:20px;box-shadow:var(--hp-shadow);min-width:0}.hpLeaguePage .leagueSectionHead{margin-bottom:16px;align-items:start}.hpLeaguePage .leagueSectionHead h3{font-size:18px;line-height:1.4}.hpLeaguePage .leagueSectionHead p{font-size:12px;line-height:1.6}.hpLeaguePage .leaguePill{padding:6px 8px;font-family:inherit;font-size:10px}.hpLeaguePage .duoPodium{align-items:stretch;gap:8px;margin:0 0 12px}.hpLeaguePage .duoChampionCard,.hpLeaguePage .duoChampion.first .duoChampionCard{min-height:0!important;height:100%;padding:15px 8px!important;border-width:1px;border-radius:15px;box-shadow:none!important;background:var(--hp-surface)!important}.hpLeaguePage .duoChampion.first .duoChampionCard{background:var(--hp-hover)!important}.hpLeaguePage .duoAvatar{width:40px;height:40px;border:1px solid var(--hp-border);border-radius:13px;font-size:17px;box-shadow:none;margin:0 auto 10px;background:var(--hp-hover);color:var(--hp-accent-text)}.hpLeaguePage .duoRankBadge{width:25px;height:25px;margin-bottom:8px;font-family:inherit;font-size:11px;box-shadow:none!important;border-width:1px}.hpLeaguePage .duoChampionName{font-size:12px;line-height:1.5}.hpLeaguePage .duoChampionMeta{font-size:10px;line-height:1.6;margin-top:4px}.hpLeaguePage .duoChampionScore{font-family:inherit;font-size:10px;max-width:100%;white-space:normal;line-height:1.4;margin-top:10px}.hpLeaguePersonCopy{min-width:0;display:block}.hpLeaguePage .leagueRows{gap:7px}.hpLeaguePage .leagueRow{grid-template-columns:26px 34px minmax(0,1fr) auto;border-width:1px;padding:10px;gap:9px;min-width:0;border-radius:12px}.hpLeaguePage .leaguePosition{width:24px;height:24px;border-radius:8px;font-family:inherit;font-size:10px}.hpLeaguePage .leagueAvatar{width:32px;height:32px;border-radius:10px;font-size:13px}.hpLeaguePage .leagueRating{display:block;font-family:inherit;font-size:11px}.hpLeaguePage .leagueMemberName{font-size:12px;line-height:1.5}.hpLeaguePage .leagueMemberMeta{font-size:10px;line-height:1.6}.hpLeagueMine{border-color:var(--hp-accent-text)!important}.hpLeaguePage .leagueEmpty{padding:20px;border-width:1px;font-size:13px}.hpLeaguePage .leagueEmpty p{margin:8px 0 16px;line-height:1.6}.hpLeaguePage .leagueEmpty b{display:block;color:var(--hp-text-primary)}.hpLeagueOutsideRank{margin-top:14px;padding-top:14px;border-top:1px solid var(--hp-border)}.hpLeagueRules{margin-top:18px;border-top:1px solid var(--hp-border);padding-top:14px}.hpLeagueRules summary,.hpLeagueAllDirections summary{cursor:pointer;font-size:12px;font-weight:750;line-height:1.6;color:var(--hp-text-primary);padding:4px 0}.hpLeagueRules p{font-size:12px;line-height:1.7;color:var(--hp-text-secondary);margin:10px 0}.hpLeagueAllDirections section+section{margin-top:12px}.hpLeagueAllDirections h4{margin:16px 0 7px;font-size:11px;color:var(--hp-text-secondary);font-weight:750}.hpLeagueActiveDirections{margin-bottom:15px}.hpLeagueSmallTitle{display:block;font-size:11px;color:var(--hp-text-secondary);margin-bottom:5px}.hpLeagueDirection{display:block;width:100%;border:1px solid transparent;border-radius:10px;padding:9px 8px;background:transparent;color:var(--hp-text-primary);text-align:left;font:inherit;cursor:pointer;min-width:0}.hpLeagueDirection:hover,.hpLeagueDirection.isSelected{background:var(--hp-hover);border-color:var(--hp-border)}.hpLeagueDirection span{display:block;line-height:1.5;font-size:12px;font-weight:750;overflow-wrap:anywhere}.hpLeagueDirection small{display:block;line-height:1.5;font-size:10px;color:var(--hp-text-secondary);margin-top:3px}.hpLeaguePage button:focus-visible,.hpLeaguePage summary:focus-visible{outline:2px solid var(--hp-focus)!important;outline-offset:3px!important}.hpLeaguePage .duoChampion:hover .duoChampionCard,.hpLeaguePage .leagueRow:hover{transform:none;filter:none;background:var(--hp-hover)!important}
.hpLeaguePage .duoPodium:has(>.duoChampion:only-child){grid-template-columns:minmax(0,1fr);max-width:300px;margin-left:auto;margin-right:auto}
  @media(max-width:1000px){.hpLeagueLayout{grid-template-columns:minmax(0,1.45fr) minmax(220px,1fr)}.hpLeaguePage .leagueBoard,.hpLeaguePage .leagueCategories{padding:16px}.hpLeagueLevels{grid-template-columns:repeat(3,minmax(0,1fr))}}
  @media(max-width:760px){.hpLeagueLayout{grid-template-columns:1fr}.hpLeaguePersonal{grid-template-columns:1fr;gap:18px;padding:20px}.hpLeagueLevels{margin-bottom:16px}.hpLeaguePersonal h3{font-size:24px}.hpLeaguePage .leagueHeading{gap:10px}.hpLeaguePage .leagueHeadingMark{flex-basis:38px;width:38px;height:38px;border-radius:12px;font-size:21px}.hpLeagueCounts{gap:7px;margin-bottom:16px}.hpLeaguePage .leagueStat{padding:13px 10px!important}.hpLeaguePage .leagueStat b{font-size:23px}.hpLeaguePage .leagueStat span{font-size:10px}.hpLeagueToolbar{gap:8px}.hpLeagueToolbar .btn{font-size:12px;padding:10px}.hpLeaguePage .leagueHeading p{font-size:12px}.hpLeaguePage .leagueHeading h2{font-size:27px}.hpLeagueStatus{height:auto;min-height:20px}.hpLeaguePage .leagueSectionHead{gap:8px}}
  @media(max-width:480px){.hpLeaguePage .duoPodium{grid-template-columns:1fr}.hpLeaguePage .duoChampionCard,.hpLeaguePage .duoChampion.first .duoChampionCard{display:grid!important;grid-template-columns:24px 36px minmax(0,1fr);align-items:center;gap:5px 8px;text-align:left;padding:11px!important}.hpLeaguePage .duoRankBadge{width:24px;height:24px;margin:0;grid-row:1/3}.hpLeaguePage .duoAvatar{width:34px;height:34px;border-radius:11px;margin:0;grid-row:1/3}.hpLeaguePage .hpLeaguePersonCopy{grid-column:3;grid-row:1}.hpLeaguePage .duoChampionScore{grid-column:3;grid-row:2;justify-self:start;margin:1px 0 0;padding:3px 6px;font-size:9px}.hpLeaguePage .duoChampionMeta{font-size:10px;margin-top:2px}.hpLeaguePage .leagueRow{grid-template-columns:24px 30px minmax(0,1fr);gap:7px}.hpLeaguePage .leagueRating{grid-column:3;text-align:left;line-height:1;margin-top:-3px}.hpLeagueLevel{padding:10px 8px}.hpLeagueLevel b{font-size:11px}.hpLeagueLevel span{font-size:10px}}
  `;
  document.head.appendChild(style);
  window.ensureProgressPanel=ensurePanel;
  window.loadProgress=loadProgress;
  window.hpointLeague={refresh:loadProgress,update,get category(){return state.category}};
})();
