/* ==========================================================================
   Socia Mind — رفتار رابط کاربری
   بدون وابستگی بیرونی؛ همهٔ درخواست‌ها با CSRF و پاسخ JSON انجام می‌شوند.
   ========================================================================== */
(function () {
  'use strict';

  var body = document.body;
  var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var chatForm = document.getElementById('chat-form');
  var chatInput = document.getElementById('chat-input');
  var chatStream = document.getElementById('chat-stream');
  var chatEnd = document.getElementById('chat-end');
  var chatError = document.getElementById('chat-error');
  var typingRow = document.getElementById('typing-indicator');
  var charCount = document.getElementById('char-count');
  var clientIdInput = document.getElementById('client-id');
  var briefPanel = document.getElementById('brief-panel');
  var suggestionsWrap = document.getElementById('suggestions-wrap');
  var statusChip = document.getElementById('status-chip');
  var titleNode = document.getElementById('conversation-title');
  var conversationRoot = document.querySelector('[data-conversation-id]');
  var maxChars = chatForm ? parseInt(chatForm.dataset.max || '1500', 10) : 1500;
  var busy = false;

  var FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

  function faNum(value) {
    return String(value).replace(/[0-9]/g, function (digit) {
      return FA_DIGITS[Number(digit)];
    });
  }

  function makeId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'c-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function setClientId() {
    if (clientIdInput) {
      clientIdInput.value = makeId();
    }
  }

  function showToast(text, isError) {
    var stack = document.getElementById('toast-stack');
    if (!stack) {
      return;
    }
    var toast = document.createElement('div');
    toast.className = 'toast' + (isError ? ' error' : '');
    toast.setAttribute('role', isError ? 'alert' : 'status');
    var span = document.createElement('span');
    span.textContent = text;
    toast.appendChild(span);
    stack.appendChild(toast);
    window.setTimeout(function () {
      toast.remove();
    }, isError ? 7000 : 4200);
  }

  function showError(message) {
    if (!chatError) {
      showToast(message, true);
      return;
    }
    chatError.textContent = message;
    chatError.hidden = false;
  }

  function clearError() {
    if (chatError) {
      chatError.hidden = true;
      chatError.textContent = '';
    }
  }

  function showTyping(label) {
    if (!typingRow) {
      return;
    }
    var textNode = typingRow.querySelector('span:last-child');
    if (textNode && label) {
      textNode.textContent = label;
    } else if (textNode) {
      textNode.textContent = 'در حال پردازش...';
    }
    typingRow.hidden = false;
  }

  function hideTyping() {
    if (typingRow) {
      typingRow.hidden = true;
    }
  }

  function scrollChat(force) {
    if (!chatStream) {
      return;
    }
    var nearBottom = chatStream.scrollHeight - chatStream.scrollTop - chatStream.clientHeight < 220;
    if (force || nearBottom) {
      chatStream.scrollTop = chatStream.scrollHeight;
    }
  }

  function appendMessages(html) {
    if (!html || !chatStream) {
      return;
    }
    var holder = document.createElement('div');
    holder.innerHTML = html;
    var nodes = Array.prototype.slice.call(holder.children);
    nodes.forEach(function (node) {
      if (!(node instanceof HTMLElement)) {
        return;
      }
      var id = node.getAttribute('data-message-id');
      if (id && chatStream.querySelector('[data-message-id="' + id + '"]')) {
        return;
      }
      if (chatEnd && chatEnd.parentNode === chatStream) {
        chatStream.insertBefore(node, chatEnd);
      } else {
        chatStream.appendChild(node);
      }
    });
  }

  function toneFor(status) {
    return {
      collecting: 'tone-collecting',
      brief_ready: 'tone-ready',
      generating: 'tone-generating',
      generated: 'tone-generated'
    }[status] || 'tone-collecting';
  }

  function syncGenerateButtons(canGenerate) {
    document.querySelectorAll('[data-generate-button]').forEach(function (button) {
      if (canGenerate) {
        button.disabled = false;
        button.removeAttribute('title');
      } else {
        button.disabled = true;
        button.setAttribute('title', 'تا آماده‌شدن و تأیید بریف، ساخت سناریو ممکن نیست.');
      }
    });
  }

  function applyState(data) {
    appendMessages(data.messages_html);

    if (statusChip && data.status) {
      statusChip.textContent = data.status_label || data.status;
      statusChip.dataset.status = data.status;
      statusChip.className = 'status-pill ' + toneFor(data.status);
    }
    if (titleNode && data.title) {
      titleNode.textContent = data.title;
      document.title = data.title + ' | Socia Mind';
    }
    if (briefPanel && typeof data.brief_html === 'string') {
      briefPanel.innerHTML = data.brief_html;
    }
    if (suggestionsWrap && typeof data.suggestions_html === 'string') {
      suggestionsWrap.innerHTML = data.suggestions_html;
    }
    if (conversationRoot) {
      var historyTitle = conversationRoot.querySelector('[data-history-title-for]');
      if (historyTitle && data.title) {
        historyTitle.textContent = data.title;
      }
    }
    if (typeof data.can_generate === 'boolean') {
      syncGenerateButtons(data.can_generate);
    }
    scrollChat(true);
  }

  function parseResponse(response) {
    return response.text().then(function (text) {
      var data = null;
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = null;
      }
      return { response: response, data: data };
    });
  }

  function describeHttpError(response) {
    if (response.status === 403) {
      return 'نشست امنیتی منقضی شده است. صفحه را دوباره بارگذاری کن و دوباره تلاش کن.';
    }
    if (response.status === 429) {
      return 'کمی صبر کن؛ تعداد درخواست‌ها زیاد شده است.';
    }
    if (response.status >= 500) {
      return 'سرور نتوانست درخواست را کامل کند. پیام‌هایت حفظ شده‌اند؛ دوباره تلاش کن.';
    }
    return 'درخواست انجام نشد. دوباره تلاش کن.';
  }

  function requestJson(url, formData, options) {
    options = options || {};
    return fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      body: formData,
      credentials: 'same-origin',
      signal: options.signal
    }).then(parseResponse);
  }

  /* ------------------------------------------------------------------------
     منوی موبایل و کشوی تاریخچه
     ------------------------------------------------------------------------ */

  var menuOpenButton = document.querySelector('[data-menu-open]');
  var navScrim = document.querySelector('.nav-scrim');

  function openMenu() {
    body.classList.add('sidebar-open');
    if (navScrim) {
      navScrim.hidden = false;
    }
    if (menuOpenButton) {
      menuOpenButton.setAttribute('aria-expanded', 'true');
    }
    var sidebar = document.getElementById('sidebar');
    var focusable = sidebar ? sidebar.querySelector('a, button:not([disabled]), input') : null;
    if (focusable) {
      focusable.focus({ preventScroll: true });
    }
  }

  function closeMenu() {
    body.classList.remove('sidebar-open');
    if (navScrim) {
      navScrim.hidden = true;
    }
    if (menuOpenButton) {
      menuOpenButton.setAttribute('aria-expanded', 'false');
      menuOpenButton.focus({ preventScroll: true });
    }
  }

  if (menuOpenButton) {
    menuOpenButton.addEventListener('click', function () {
      if (body.classList.contains('sidebar-open')) {
        closeMenu();
      } else {
        openMenu();
      }
    });
  }
  document.querySelectorAll('[data-menu-close]').forEach(function (button) {
    button.addEventListener('click', closeMenu);
  });

  var historyToggle = document.querySelector('[data-history-toggle]');
  var historyPanel = document.getElementById('history-panel');
  var historyScrim = document.querySelector('.history-scrim');

  function openHistory() {
    body.classList.add('history-open');
    if (historyScrim) {
      historyScrim.hidden = false;
    }
    if (historyToggle) {
      historyToggle.setAttribute('aria-expanded', 'true');
    }
    var closeButton = historyPanel ? historyPanel.querySelector('[data-history-close]') : null;
    if (closeButton) {
      closeButton.focus({ preventScroll: true });
    }
  }

  function closeHistory() {
    body.classList.remove('history-open');
    if (historyScrim) {
      historyScrim.hidden = true;
    }
    if (historyToggle) {
      historyToggle.setAttribute('aria-expanded', 'false');
      historyToggle.focus({ preventScroll: true });
    }
  }

  if (historyToggle) {
    historyToggle.addEventListener('click', function () {
      if (body.classList.contains('history-open')) {
        closeHistory();
      } else {
        openHistory();
      }
    });
  }
  document.querySelectorAll('[data-history-close]').forEach(function (button) {
    button.addEventListener('click', closeHistory);
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
      return;
    }
    if (body.classList.contains('sidebar-open')) {
      closeMenu();
    }
    if (body.classList.contains('history-open')) {
      closeHistory();
    }
  });

  /* ------------------------------------------------------------------------
     شمارندهٔ نویسه و رشد خودکار جعبهٔ پیام
     ------------------------------------------------------------------------ */

  function resizeInput() {
    if (!chatInput) {
      return;
    }
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
  }

  function updateCounter() {
    if (!chatInput || !charCount) {
      return;
    }
    var length = chatInput.value.length;
    charCount.textContent = faNum(length);
    if (length > maxChars * 0.92) {
      charCount.style.color = 'var(--amber)';
    } else {
      charCount.style.color = '';
    }
  }

  if (chatInput) {
    chatInput.addEventListener('input', function () {
      updateCounter();
      resizeInput();
    });
    chatInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        if (chatForm && !busy) {
          chatForm.requestSubmit();
        }
      }
    });
    updateCounter();
    resizeInput();
  }
  setClientId();

  function focusComposer(prefill) {
    if (!chatInput) {
      return;
    }
    if (typeof prefill === 'string') {
      chatInput.value = prefill;
      updateCounter();
      resizeInput();
    }
    chatInput.focus({ preventScroll: false });
    chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
    if (chatInput.scrollIntoView) {
      chatInput.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  /* ------------------------------------------------------------------------
     ارسال پیام چت
     ------------------------------------------------------------------------ */

  function setChatBusy(state) {
    busy = state;
    if (!chatForm) {
      return;
    }
    chatForm.classList.toggle('is-loading', state);
    chatForm.setAttribute('aria-busy', state ? 'true' : 'false');
    var sendButton = document.getElementById('send-btn');
    if (sendButton) {
      sendButton.disabled = state;
      var label = sendButton.querySelector('span');
      if (label) {
        label.textContent = state ? 'ارسال...' : 'ارسال';
      }
    }
    if (chatInput) {
      chatInput.disabled = state;
    }
  }

  if (chatForm) {
    chatForm.addEventListener('submit', function (event) {
      event.preventDefault();
      if (busy) {
        return;
      }
      var submitted = chatInput ? chatInput.value.trim() : '';
      if (!submitted) {
        showError('متن پیام خالی است. یک جمله بنویس و دوباره ارسال کن.');
        if (chatInput) {
          chatInput.focus();
        }
        return;
      }
      if (submitted.length > maxChars) {
        showError('پیام بلندتر از سقف مجاز است.');
        return;
      }
      if (clientIdInput && !clientIdInput.value) {
        setClientId();
      }

      var formData = new FormData(chatForm);
      formData.set('text', submitted);
      clearError();
      showTyping('در حال پردازش پیام...');
      setChatBusy(true);

      requestJson(chatForm.action, formData)
        .then(function (result) {
          if (result.data) {
            applyState(result.data);
          }
          if (!result.response.ok || (result.data && result.data.ok === false)) {
            var message = (result.data && result.data.error) || describeHttpError(result.response);
            showError(message);
            showToast(message, true);
            return;
          }
          if (chatInput && chatInput.value.trim() === submitted) {
            chatInput.value = '';
            updateCounter();
            resizeInput();
          }
          setClientId();
          showToast(result.data && result.data.duplicate ? 'این پیام قبلاً ثبت شده بود.' : 'پیام ثبت شد.');
        })
        .catch(function () {
          showError('ارتباط با سرور برقرار نشد. پیام تو در جعبهٔ متن باقی مانده است؛ دوباره ارسال کن.');
          showToast('ارتباط با سرور برقرار نشد.', true);
        })
        .finally(function () {
          hideTyping();
          setChatBusy(false);
          scrollChat(true);
        });
    });
  }

  /* ------------------------------------------------------------------------
     دکمه‌های پیشنهاد پاسخ
     ------------------------------------------------------------------------ */

  document.addEventListener('click', function (event) {
    var chip = event.target.closest('[data-send]');
    if (!chip) {
      return;
    }
    event.preventDefault();
    if (!chatInput || busy) {
      return;
    }
    chatInput.value = chip.dataset.send || chip.textContent.trim();
    updateCounter();
    resizeInput();
    if (chatForm) {
      chatForm.requestSubmit();
    }
  });

  /* ------------------------------------------------------------------------
     ساخت سناریو — فقط با فرم دارای confirm=1
     ------------------------------------------------------------------------ */

  document.addEventListener('submit', function (event) {
    var form = event.target.closest('[data-generate-form]');
    if (!form) {
      return;
    }
    event.preventDefault();
    if (form.dataset.busy === '1') {
      return;
    }
    form.dataset.busy = '1';
    clearError();
    showTyping('در حال ساخت سناریو... این مرحله ممکن است تا یک دقیقه طول بکشد.');
    form.querySelectorAll('button').forEach(function (button) {
      button.disabled = true;
    });

    requestJson(form.action, new FormData(form))
      .then(function (result) {
        if (result.data) {
          applyState(result.data);
        }
        if (!result.response.ok || (result.data && result.data.ok === false)) {
          var message = (result.data && result.data.error) || describeHttpError(result.response);
          showError(message);
          showToast(message, true);
          return;
        }
        showToast('سناریو ساخته شد. خروجی را در گفتگو ببین.');
      })
      .catch(function () {
        var message = 'ارتباط با سرور برقرار نشد. بریف و پیام‌ها حفظ شده‌اند؛ دوباره تلاش کن.';
        showError(message);
        showToast(message, true);
      })
      .finally(function () {
        form.dataset.busy = '0';
        hideTyping();
        form.querySelectorAll('button').forEach(function (button) {
          button.disabled = false;
        });
        var canGenerate = !statusChip || statusChip.dataset.status === 'brief_ready';
        syncGenerateButtons(canGenerate);
        scrollChat(true);
      });
  });

  /* ------------------------------------------------------------------------
     کپی سناریو
     ------------------------------------------------------------------------ */

  function fallbackCopy(text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'readonly');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    area.style.top = '0';
    document.body.appendChild(area);
    area.select();
    var copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (error) {
      copied = false;
    }
    area.remove();
    return copied;
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-copy-scenario]');
    if (!button) {
      return;
    }
    event.preventDefault();
    var card = button.closest('[data-scenario-card]');
    if (!card) {
      return;
    }
    var raw = card.querySelector('.scenario-raw');
    var text = raw ? raw.textContent.trim() : (card.querySelector('.scenario-text') || {}).innerText || '';
    if (!text) {
      showToast('متنی برای کپی پیدا نشد.', true);
      return;
    }
    var done = function (ok) {
      if (ok) {
        showToast('سناریو در حافظه کپی شد.');
      } else {
        showToast('کپی خودکار ممکن نشد؛ متن را دستی انتخاب کن.', true);
      }
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () {
        done(true);
      }).catch(function () {
        done(fallbackCopy(text));
      });
    } else {
      done(fallbackCopy(text));
    }
  });

  /* ------------------------------------------------------------------------
     تعامل‌های عمومی
     ------------------------------------------------------------------------ */

  document.addEventListener('click', function (event) {
    var briefButton = event.target.closest('[data-open-brief]');
    if (briefButton) {
      var editor = document.getElementById('brief-editor');
      if (editor) {
        editor.open = true;
        editor.scrollIntoView({ behavior: 'smooth', block: 'center' });
        var firstInput = editor.querySelector('textarea, input, button');
        if (firstInput) {
          window.setTimeout(function () {
            firstInput.focus({ preventScroll: true });
          }, 260);
        }
      }
      return;
    }

    var focusButton = event.target.closest('[data-focus-chat]');
    if (focusButton) {
      event.preventDefault();
      focusComposer(focusButton.dataset.prefill || '');
    }
  });

  document.addEventListener('submit', function (event) {
    var form = event.target;
    var message = form.getAttribute && form.getAttribute('data-confirm');
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  /* ------------------------------------------------------------------------
     وضعیت اولیه
     ------------------------------------------------------------------------ */

  syncGenerateButtons(!statusChip || statusChip.dataset.status === 'brief_ready');
  if (chatStream) {
    window.requestAnimationFrame(function () {
      scrollChat(true);
    });
  }
})();
