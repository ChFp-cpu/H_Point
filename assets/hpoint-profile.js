/* Stable profile editor: explicit save/cancel, account-bound drafts and errors. */
(()=>{
 'use strict';
 const $=id=>document.getElementById(id),account=()=>String(window.hpointWorkspace?.state?.data?.current_user_id??'');
 let owner='',ctx=null;
 function values(user){return {name:String(user.name||''),city:String(user.city||''),bio:String(user.bio||'')}}
 function write(data){for(const key of ['name','city','bio'])ctx.form.elements[key].value=data[key];counter()}
 function counter(){if(ctx)ctx.form.querySelector('[data-bio-count]').textContent=ctx.form.elements.bio.value.length+' / 500'}
 function relevant(current){return current===ctx&&current.owner===account()&&current.form.isConnected}
 function mount(host,user){
  if(!host||!user)return;
  if(owner!==account()){owner=account();ctx?.form.remove();ctx=null}
  if(!ctx){
   const card=document.createElement('section');card.className='workspaceCard profileEditor';
   card.innerHTML='<h2>Основные данные</h2><p class="muted">Имя и описание видны участникам. Контакты настраиваются отдельно.</p><form id="wsProfileForm" autocomplete="off"><label for="wsName">Имя<input id="wsName" name="name" class="input" required minlength="2" maxlength="50" autocomplete="name" placeholder="Как к вам обращаться"></label><label for="wsCity">Город<input id="wsCity" name="city" class="input" maxlength="80" autocomplete="address-level2" placeholder="Город или населённый пункт"></label><label for="wsBio">О себе<textarea id="wsBio" name="bio" class="input textarea" maxlength="500" rows="3" placeholder="Чем занимаетесь и с чем можете помочь"></textarea><small data-bio-count></small></label><div class="workspaceActions"><button class="btn grad" type="submit" data-profile-save>Сохранить изменения</button><button class="btn light" type="button" data-profile-cancel>Отменить изменения</button></div><p class="profileEditorNotice" role="status" aria-live="polite"></p></form>';
   ctx={owner,card,form:card.querySelector('form'),dirty:false,busy:false,latest:values(user)};
   const current=ctx,form=current.form,notice=form.querySelector('[role=status]');
   form.addEventListener('input',()=>{if(!relevant(current))return;current.dirty=true;notice.textContent='Есть несохранённые изменения';notice.dataset.error='false';counter()});
   form.querySelector('[data-profile-cancel]').addEventListener('click',()=>{if(current.busy||!relevant(current))return;current.dirty=false;write(current.latest);notice.textContent='Изменения отменены';notice.dataset.error='false';form.elements.name.focus({preventScroll:true})});
   form.addEventListener('submit',async event=>{
    event.preventDefault();if(current.busy||!form.reportValidity())return;
    const payload={name:form.elements.name.value.trim(),city:form.elements.city.value.trim(),bio:form.elements.bio.value.trim()};
    current.busy=true;notice.textContent='Сохраняем…';notice.dataset.error='false';for(const control of form.elements)control.disabled=true;
    try{
     const response=await fetch('/api/profile',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),result=await response.json();
     if(current!==ctx||current.owner!==account())return;if(!response.ok||result.ok===false)throw Error(result.error||'Не удалось сохранить профиль. Повторите попытку.');
     current.latest=values(result.user||payload);current.dirty=false;write(current.latest);
     await window.hpointWorkspace.refresh();if(current===ctx&&current.owner===account()){notice.textContent='Профиль сохранён';notice.dataset.error='false'}
    }catch(error){if(current===ctx&&current.owner===account()){notice.textContent=error.message||'Не удалось сохранить профиль. Повторите попытку.';notice.dataset.error='true'}}
    finally{current.busy=false;for(const control of form.elements)control.disabled=false}
   });
   write(ctx.latest);
  }
  ctx.latest=values(user);if(!ctx.dirty&&!ctx.busy)write(ctx.latest);
  if(ctx.card.parentElement!==host)host.replaceChildren(ctx.card);
 }
 const style=document.createElement('style');style.textContent='.profileEditor{min-width:0}.profileEditor h2{margin:0;font-size:23px}.profileEditor>p{font-size:12px;line-height:1.7;margin:10px 0 20px}.profileEditor form{display:grid;gap:15px}.profileEditor label{display:grid;gap:7px;font-size:13px;font-weight:650;min-width:0}.profileEditor .input{width:100%;min-width:0;max-width:100%;font:inherit}.profileEditor small{font-size:11px;color:var(--hp-text-secondary);font-weight:400;text-align:right}.profileEditorNotice{min-height:20px;margin:0;font-size:12px;line-height:1.6;color:var(--hp-accent-text);overflow-wrap:anywhere}.profileEditorNotice[data-error=true]{color:var(--hp-danger)}.profileEditor [disabled]{opacity:.65}@media(max-width:600px){.profileEditor .workspaceActions>.btn{width:100%;white-space:normal;min-height:44px}}';document.head.appendChild(style);
 window.hpointProfile={mount};
})();
