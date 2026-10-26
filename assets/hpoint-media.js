/* Photographs and participant lists. All image URLs remain access-controlled. */
(() => {
  'use strict';
  if (window.HPointMedia) return;
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  let requestFiles = [], requestField = null, enhancementQueued = false, mediaOwner = null;
  const chatFiles = new Map();
  const currentChat = () => Number(window.hpointWorkspace?.state?.chatId || 0);
  const notify = message => typeof window.toast === 'function' ? window.toast(message) : console.warn(message);

  async function api(url, options) {
    if (typeof window.api === 'function') return window.api(url, options);
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Не удалось выполнить действие.');
    return data;
  }

  function gallery(photos) {
    const rows = (Array.isArray(photos) ? photos : []).filter(photo => /^\/api\/photos\?id=[a-f0-9]{32}$/.test(photo.url || ''));
    return rows.length ? '<div class="hpointPhotoGallery" aria-label="Прикреплённые фотографии">' + rows.map(photo =>
      '<a href="' + photo.url + '" target="_blank" rel="noopener" aria-label="Открыть фото"><img loading="lazy" src="' + photo.url + '" alt="Прикреплённая фотография" width="' + Number(photo.width || 240) + '" height="' + Number(photo.height || 180) + '"></a>').join('') + '</div>' : '';
  }

  function resizePhoto(file) {
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) return Promise.reject(new Error('Выберите фото JPEG, PNG или WebP.'));
    if (file.size > 15 * 1024 * 1024) return Promise.reject(new Error('Исходное фото должно быть не больше 15 МБ.'));
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Не удалось прочитать фото.'));
      reader.onload = () => {
        const image = new Image();
        image.onerror = () => reject(new Error('Не удалось открыть фото.'));
        image.onload = () => {
          if (!image.naturalWidth || image.naturalWidth * image.naturalHeight > 20_000_000) { reject(new Error('Уменьшите фото до 20 мегапикселей.')); return; }
          const scale = Math.min(1, 1920 / Math.max(image.naturalWidth, image.naturalHeight));
          const canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
          const context = canvas.getContext('2d');
          context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          const value = canvas.toDataURL('image/jpeg', .85);
          if (value.length > 4 * 1024 * 1024) { reject(new Error('Не удалось уменьшить фото до 3 МБ.')); return; }
          resolve(value);
        };
        image.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function preview(widget, photos) {
    const host = widget.querySelector('.hpointPhotoPreviews');
    host.innerHTML = photos.map((photo, index) => '<div><img src="' + photo + '" alt="Выбранное фото"><button class="btn light" type="button" data-photo-remove="' + index + '" aria-label="Убрать фото">Убрать</button></div>').join('');
  }

  function picker(kind) {
    const widget = document.createElement('div');
    widget.className = 'hpointPhotoPicker'; widget.dataset.photoKind = kind;
    widget.innerHTML = '<label class="hpointPhotoLabel">' + (kind === 'request' ? 'Фото к помощи' : 'Фото в чат') +
      '<input type="file" accept="image/jpeg,image/png,image/webp" multiple aria-label="' + (kind === 'request' ? 'Добавить фото к помощи' : 'Прикрепить фото в чате') + '"></label><small>До 3 фото. Фото автоматически уменьшаются.</small><div class="hpointPhotoPreviews"></div><p class="hpointPhotoStatus" role="status"></p>';
    const get = () => kind === 'request' ? requestFiles : (chatFiles.get(Number(widget.dataset.chatId)) || []);
    const set = values => kind === 'request' ? (requestFiles = values) : chatFiles.set(Number(widget.dataset.chatId), values);
    widget.querySelector('input').addEventListener('change', async event => {
      const files = [...event.target.files], status = widget.querySelector('[role="status"]');
      try {
        if (get().length + files.length > 3) throw new Error('Можно прикрепить до трёх фотографий.');
        event.target.disabled = true; status.textContent = 'Подготавливаем фото…';
        const added = await Promise.all(files.map(resizePhoto));
        set([...get(), ...added]); preview(widget, get()); status.textContent = 'Фото прикреплены. Они отправятся вместе с ' + (kind === 'request' ? 'заявкой.' : 'сообщением.');
      } catch (error) { status.textContent = error.message; }
      finally { event.target.disabled = false; event.target.value = ''; }
    });
    widget.addEventListener('click', event => {
      const button = event.target.closest('[data-photo-remove]');
      if (!button) return;
      set(get().filter((_, index) => index !== Number(button.dataset.photoRemove)));
      preview(widget, get()); widget.querySelector('[role="status"]').textContent = '';
    });
    return widget;
  }

  function enhance() {
    const owner=String(window.hpointWorkspace?.state?.data?.current_user_id||'');
    if(owner!==mediaOwner){chatFiles.clear();requestFiles=[];requestField=null;mediaOwner=owner}
    const field = $('qw');
    if (field && field !== requestField) { requestField = field; requestFiles = []; }
    if (!field && requestField && !requestField.isConnected) { requestField = null; requestFiles = []; }
    if (field && !$('requestPhotoPicker')) {
      const target = document.querySelector('.requestStep[data-request-step="2"]') || $('qd')?.parentElement;
      if (target) { const widget = picker('request'); widget.id = 'requestPhotoPicker'; target.appendChild(widget); }
    }
    const form = document.querySelector('.workspaceChatForm'), chatId = currentChat();
    if (form && chatId && !form.querySelector('.hpointPhotoPicker')) {
      const widget = picker('chat'); widget.dataset.chatId = String(chatId); form.appendChild(widget); preview(widget, chatFiles.get(chatId) || []);
    }
    const state = window.hpointWorkspace?.state;
    if (state?.chat?.messages) {
      const nodes = document.querySelectorAll('.workspaceChatPanel .workspaceMessage');
      state.chat.messages.forEach((message, index) => {
        if (nodes[index] && !nodes[index].querySelector('.hpointPhotoGallery')) nodes[index].insertAdjacentHTML('beforeend', gallery(message.photos));
      });
    }
    const requests = [...(state?.data?.requests || []), ...(state?.data?.open || [])];
    document.querySelectorAll('.workspaceRequest').forEach(node => {
      if (node.querySelector('.hpointPhotoGallery')) return;
      const button = node.querySelector('[data-id]'), row = requests.find(request => Number(request.id) === Number(button?.dataset.id));
      const target = node.querySelector('.workspaceRequestMain');
      if (row && target) target.insertAdjacentHTML('beforeend', gallery(row.photos));
    });
  }

  async function sendAttachedMessage(button) {
    const id=currentChat(),photos=(chatFiles.get(id)||[]).slice();
    if(!id||!photos.length||button.disabled)return;
    if(typeof window.hpointWorkspace?.sendChat!=='function'){notify('Обновите страницу, чтобы отправить фото.');return}
    await window.hpointWorkspace.sendChat(photos);
  }

  async function showParticipants(id) {
    try {
      const data = await api('/api/events/participants?id=' + Number(id)), modal = $('modal'), body = $('modalbody');
      if (!modal || !body) return;
      modal.style.display = 'flex';
      body.innerHTML = '<h2>Участники · ' + escape(data.title) + '</h2><p class="muted">Записались на мероприятие</p><div class="hpointParticipantList">' +
        ((data.participants || []).map(person => '<button class="hpointParticipant btn light" type="button" data-participant-profile="' + Number(person.profile_id) + '"><span class="hpointParticipantAvatar">' + escape((person.name || '?').slice(0, 1)) + '</span><span>' + escape(person.name || 'Участник') + '</span></button>').join('') || '<p class="muted">Пока никто не записался.</p>') + '</div>';
    } catch (error) { notify(error.message); }
  }

  // Existing eventCard is a global renderer. Decorate it after inline app
  // setup, keeping the participant button available even for full events.
  if (typeof window.eventCard === 'function') {
    const original = window.eventCard;
    window.eventCard = function(event) {
      return original(event).replace('<div class="eventActions">', '<div class="eventActions"><button class="btn light" type="button" data-event-participants="' + Number(event.id) + '">Участники</button>');
    };
  }
  document.addEventListener('click', event => {
    const send = event.target.closest('[data-ws-action="chat-send"]');
    const publishing = event.target.closest('#createRequestButton');
    if ((send && document.querySelector('.workspaceChatForm .hpointPhotoPicker input:disabled')) ||
        (publishing && document.querySelector('#requestPhotoPicker input:disabled'))) {
      event.preventDefault(); event.stopImmediatePropagation(); notify('Дождитесь подготовки фотографий.'); return;
    }
    if (send && (chatFiles.get(currentChat()) || []).length) {
      event.preventDefault(); event.stopImmediatePropagation(); sendAttachedMessage(send); return;
    }
    const participants = event.target.closest('[data-event-participants]');
    if (participants) { event.preventDefault(); showParticipants(Number(participants.dataset.eventParticipants)); return; }
    const profile = event.target.closest('[data-participant-profile]');
    if (profile && typeof window.openCommunityProfile === 'function') window.openCommunityProfile(Number(profile.dataset.participantProfile));
  }, true);

  const style = document.createElement('style');
  style.textContent = '.hpointPhotoPicker{grid-column:1/-1;min-width:0;width:100%;box-sizing:border-box;margin-top:10px;font:inherit}.hpointPhotoLabel{display:grid;min-width:0;gap:8px;font-weight:700}.hpointPhotoPicker input{display:block;min-width:0;width:100%;max-width:100%;box-sizing:border-box;overflow:hidden;font:inherit}.hpointPhotoPicker small,.hpointPhotoStatus{display:block;font:inherit;font-size:13px;line-height:1.5;opacity:.8}.hpointPhotoPreviews,.hpointPhotoGallery{display:flex;gap:8px;flex-wrap:wrap;max-width:100%;margin:10px 0}.hpointPhotoPreviews>div{display:grid;gap:4px}.hpointPhotoPreviews img,.hpointPhotoGallery img{display:block;width:92px;height:92px;object-fit:cover;border-radius:12px}.hpointPhotoPreviews button{min-height:36px!important;font-size:12px!important;padding:5px 8px!important}.hpointPhotoGallery a{max-width:100%;border-radius:12px;overflow:hidden}.hpointParticipantList{display:grid;gap:10px}.hpointParticipant{display:flex!important;align-items:center;gap:12px;text-align:left!important;justify-content:flex-start!important;font:inherit;white-space:normal!important}.hpointParticipantAvatar{display:grid;place-items:center;flex:0 0 38px;width:38px;height:38px;border-radius:50%;background:#b8f36b;color:#172417;font-weight:800}';
  document.head.appendChild(style);
  window.HPointMedia = {
    requestPhotos:() => requestFiles.slice(),
    clearRequestPhotos:() => { requestFiles = []; },
    chatPhotos:() => (chatFiles.get(currentChat()) || []).slice(),
    clearChatPhotos:(id=currentChat(),form=null) => {
      chatFiles.delete(Number(id));
      const source=form||document.querySelector('.workspaceChatForm[data-chat-id="'+Number(id)+'"]'),widget=source?.querySelector('.hpointPhotoPicker');
      if(widget){preview(widget,[]);const status=widget.querySelector('[role="status"]');if(status)status.textContent='';const input=widget.querySelector('input[type="file"]');if(input)input.value=''}
    },
    gallery, showParticipants, enhance
  };
  new MutationObserver(() => {
    if (enhancementQueued) return;
    enhancementQueued = true; requestAnimationFrame(() => { enhancementQueued = false; enhance(); });
  }).observe(document.body, {childList:true, subtree:true});
  enhance();
})();
