/* One shared catalog for requests, helper preferences and category leagues. */
(()=>{
  'use strict';
  const data=window.hpointHelpCategoriesData;
  if(!Array.isArray(data?.catalog)||!Array.isArray(data?.groups))return;
  const catalog=data.catalog,groups=data.groups;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function options(selected='',empty='Все направления'){
    return '<option value="">'+esc(empty)+'</option>'+groups.map(group=>'<optgroup label="'+esc(group.title)+'">'+catalog.filter(item=>item.group===group.key).map(item=>'<option value="'+esc(item.key)+'"'+(selected===item.key?' selected':'')+'>'+esc(item.title)+'</option>').join('')+'</optgroup>').join('');
  }
  function preferences(selected=[]){
    return '<div class="hpHelpCategoryGroups">'+groups.map(group=>'<fieldset class="hpHelpCategoryGroup"><legend>'+esc(group.title)+'</legend><div>'+catalog.filter(item=>item.group===group.key).map(item=>'<label title="'+esc(item.hint)+'"><input type="checkbox" id="wsHelperCategory_'+esc(item.key)+'" name="helperCategory" value="'+esc(item.key)+'"'+(selected.includes(item.key)?' checked':'')+'><span>'+esc(item.label)+'</span></label>').join('')+'</div></fieldset>').join('')+'</div>';
  }
  window.hpointHelpCategories={catalog,groups,options,preferences};
  const style=document.createElement('style');style.textContent=`
    .helperPreferences .hpHelpCategoryGroups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
    .helperPreferences .hpHelpCategoryGroup{min-width:0;border:0;padding:0;margin:0}
    .helperPreferences .hpHelpCategoryGroup legend{margin:0 0 8px;padding:0;font-size:14px;font-weight:750;color:var(--hp-text-primary)}
    .helperPreferences .hpHelpCategoryGroup>div{display:grid;gap:5px}
    .helperPreferences .hpHelpCategoryGroup label{display:flex;align-items:center;gap:10px;min-height:42px;padding:7px 10px;border:1px solid transparent;border-radius:10px;color:var(--hp-text-primary);font-size:14px;line-height:1.45;cursor:pointer}
    .helperPreferences .hpHelpCategoryGroup label:has(input:checked){background:var(--hp-hover);border-color:var(--hp-border)}
    .helperPreferences .hpHelpCategoryGroup input{width:18px;height:18px;flex:none;margin:0;accent-color:var(--hp-accent-text)}
    .helperPreferences .hpHelpCategoryGroup label:focus-within{outline:2px solid var(--hp-focus);outline-offset:1px}
    .hpRequestCategoryHint{display:block;margin:6px 0 0;color:var(--hp-text-secondary);font-size:12px;font-weight:450;line-height:1.55}
    .workspaceHelpSearch:has(#wsRequestCategory){display:flex;flex-wrap:wrap;gap:10px}
    .workspaceHelpSearch:has(#wsRequestCategory)>.input{flex:1 1 180px;min-width:0;width:auto}
    .workspaceHelpSearch:has(#wsRequestCategory)>.btn{flex:0 0 auto}
    @media(max-width:560px){.helperPreferences .hpHelpCategoryGroups{grid-template-columns:1fr;gap:20px}.workspaceHelpSearch:has(#wsRequestCategory)>.input{flex-basis:100%;width:100%}.workspaceHelpSearch:has(#wsRequestCategory)>.btn{width:100%}}
  `;document.head.appendChild(style);
  const original=window.requestForm;
  window.requestForm=function(...args){
    const result=original.apply(this,args),select=document.getElementById('qc');
    if(select){
      select.innerHTML=options('','Выберите направление');select.required=true;select.setAttribute('aria-describedby','requestCategoryHint');
      const hint=document.createElement('small');hint.id='requestCategoryHint';hint.className='hpRequestCategoryHint';hint.textContent='Выберите близкое направление — так проще найти помощника.';select.after(hint);
      select.addEventListener('change',()=>{hint.textContent=catalog.find(item=>item.key===select.value)?.hint||'Выберите близкое направление — так проще найти помощника.'});
    }
    return result;
  };
  const step=window.requestWizardStep;
  function hasDirection(){
    const select=document.getElementById('qc');if(select&&catalog.some(item=>item.key===select.value))return true;
    const error=document.getElementById('rqerr');if(error)error.textContent='Выберите направление помощи.';select?.focus();return false;
  }
  window.requestWizardStep=function(delta){
    if(delta>0&&(window.hpointRequestStep||0)===0&&!hasDirection())return;
    return step(delta);
  };
  for(const name of ['createReq','sendReq']){const publish=window[name];window[name]=function(...args){if(!hasDirection())return;return publish.apply(this,args)}}
  const search=document.getElementById('searchCategory');if(search)search.innerHTML=options();
})();
