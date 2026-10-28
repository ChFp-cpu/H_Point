/* Only explicitly published services enter the activity directory. */
(()=>{
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let rows=[],loadedAt=0,pending=null,query='';
  function paint(host){
    if(!host?.isConnected)return;
    const matching=rows.filter(row=>(row.title+' '+row.organization_title+' '+row.description).toLocaleLowerCase('ru-RU').includes(query.toLocaleLowerCase('ru-RU')));
    const list=host.querySelector('.activityServicesList');if(!list)return;
    list.innerHTML=matching.length?matching.map(row=>'<article class="activityService"><span class="workspaceKicker">'+escape(row.organization_title)+'</span><h3>'+escape(row.title)+'</h3><p>'+escape(row.description)+'</p><div><b>'+Number(row.price_rub).toLocaleString('ru-RU')+' тест. ₽</b><small>'+Number(row.duration_minutes)+' мин.</small></div><a class="btn light" href="'+escape(row.organization_url)+'">Об организации →</a></article>').join(''):'<p class="muted">'+(query?'Услуг по этому запросу нет.':'Здесь появятся услуги организаций, которые опубликовали свою страницу.')+'</p>';
  }
  async function load(host){
    if(pending){await pending;paint(host);return}
    if(Date.now()-loadedAt<30000){paint(host);return}
    pending=(async()=>{const response=await fetch('/api/organizations/services',{credentials:'same-origin'}),data=await response.json();if(!response.ok||!data.ok)throw Error('Не удалось загрузить услуги');rows=data.services||[];loadedAt=Date.now()})();
    try{await pending;paint(host)}catch(error){if(host.isConnected)host.querySelector('.activityServicesList').innerHTML='<p class="muted">Услуги временно недоступны. <button class="workspacePromoLink" type="button" data-services-retry>Повторить</button></p>'}finally{pending=null}
  }
  function mount(host){
    if(!host)return;
    if(!host.querySelector('.activityServicesList')){
      host.innerHTML='<section class="workspaceCard activityDirectory" aria-labelledby="activityServicesTitle"><div class="activityDirectoryHeading"><div><span class="workspaceKicker">ДЛЯ РАБОТЫ</span><h2 id="activityServicesTitle">Услуги организаций</h2><p class="muted">Специалисты и команды в H-Point.</p></div><button class="btn light" type="button" onclick="hpointCommercial.open()">Мой кабинет</button></div><form class="activityServicesSearch"><input class="input" type="search" maxlength="120" aria-label="Поиск услуг организаций" placeholder="Услуга или организация"><button class="btn light" type="submit">Найти</button></form><div class="activityServicesList" aria-live="polite"><p class="muted">Загружаем услуги…</p></div></section>';
      host.querySelector('input').value=query;
      host.querySelector('form').addEventListener('submit',event=>{event.preventDefault();query=host.querySelector('input').value.trim();paint(host)});
      host.addEventListener('click',event=>{if(event.target.closest('[data-services-retry]'))load(host)});
    }
    load(host);
  }
  window.hpointOrganizations={mount,invalidate(){loadedAt=0}};
  window.addEventListener('hpoint:work-updated',()=>{loadedAt=0});
})();
