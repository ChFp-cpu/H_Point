/* Public organisation pages share the application's gestures and photo fallback. */
(()=>{
 'use strict';
 document.addEventListener('wheel',event=>{if(event.ctrlKey)event.preventDefault()},{passive:false});
 for(const type of ['gesturestart','gesturechange','gestureend'])document.addEventListener(type,event=>event.preventDefault(),{passive:false});
 document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&!event.altKey&&!event.isComposing&&['+','=','-','_','Add','Subtract'].includes(event.key))event.preventDefault()},true);
 function photoFallback(image){
  if(!image.classList?.contains('hpPhotoImage'))return;
  const frame=image.closest('.hpPhoto');
  if(frame){frame.classList.add('hpPhotoUnavailable');frame.setAttribute('role','img');frame.setAttribute('aria-label',image.alt||'Иллюстрация направления');image.remove()}
 }
 document.addEventListener('error',event=>photoFallback(event.target),true);
 // Eager images can fail before this end-of-body script has loaded.
 for(const image of document.querySelectorAll('.hpPhotoImage'))if(image.complete&&!image.naturalWidth)photoFallback(image);
})();
