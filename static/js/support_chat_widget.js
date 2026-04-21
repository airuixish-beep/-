(function () {
  const root = document.getElementById('support-chat-widget');
  if (!root) return;

  const toggleButton = root.querySelector('[data-role="toggle"]');
  const panel = root.querySelector('[data-role="panel"]');
  const teaser = root.querySelector('[data-role="teaser"]');
  const dismissTeaserButton = root.querySelector('[data-role="dismiss-teaser"]');
  const closeButton = root.querySelector('[data-role="close"]');
  const form = root.querySelector('[data-role="form"]');
  const messagesNode = root.querySelector('[data-role="messages"]');
  const errorNode = root.querySelector('[data-role="error"]');
  const badgeNode = root.querySelector('[data-role="badge"]');
  const detailsToggle = root.querySelector('[data-role="details-toggle"]');
  const detailsFields = root.querySelector('[data-role="details-fields"]');
  const submitButton = root.querySelector('[data-role="submit"]');
  const statusNode = root.querySelector('[data-role="status"]');

  const sessionUrl = root.dataset.sessionUrl;
  const messagesUrl = root.dataset.messagesUrl;
  const sendUrl = root.dataset.sendUrl;
  const readUrl = root.dataset.readUrl;
  const defaultLanguage = root.dataset.defaultLanguage || 'en';
  const teaserDelay = Number(root.dataset.teaserDelay || 8000);

  const teaserDismissedKey = 'support-chat-teaser-dismissed';
  const panelOpenedKey = 'support-chat-panel-opened';

  let initialized = false;
  let pollInterval = 3000;
  let backgroundPollInterval = 9000;
  let pollTimer = null;
  let lastMessageId = 0;
  let unreadCount = 0;
  let isSending = false;
  let hasSentMessage = false;

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>\"']/g, function (char) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char];
    });
  }

  function getCsrfToken() {
    return document.cookie.split('; ').find(function (item) {
      return item.startsWith('csrftoken=');
    })?.split('=')[1] || '';
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Request failed');
    }
    return data;
  }

  function isPanelOpen() {
    return !panel.classList.contains('hidden');
  }

  function isNearBottom() {
    return messagesNode.scrollHeight - messagesNode.scrollTop - messagesNode.clientHeight < 80;
  }

  function setDetailsExpanded(expanded) {
    detailsFields.classList.toggle('hidden', !expanded);
    detailsToggle.textContent = expanded ? 'Hide contact details' : 'Add your name or email for follow-up';
  }

  function setSendingState(sending) {
    isSending = sending;
    submitButton.disabled = sending;
    submitButton.textContent = sending ? 'Sending...' : 'Send';
    statusNode.textContent = sending ? 'Sending your message…' : 'Usually replies within a few hours.';
  }

  function showError(message) {
    errorNode.textContent = message;
    errorNode.classList.remove('hidden');
  }

  function clearError() {
    errorNode.textContent = '';
    errorNode.classList.add('hidden');
  }

  function hideTeaser() {
    teaser.classList.add('hidden');
  }

  function maybeShowTeaser() {
    if (localStorage.getItem(teaserDismissedKey) === '1' || localStorage.getItem(panelOpenedKey) === '1') {
      return;
    }
    window.setTimeout(function () {
      if (!isPanelOpen()) {
        teaser.classList.remove('hidden');
      }
    }, teaserDelay);
  }

  function renderMessage(message) {
    const mine = message.sender_type === 'visitor';
    return '<article class="' + (mine ? 'text-right' : 'text-left') + '">'
      + '<div class="inline-block max-w-[85%] rounded-2xl border px-4 py-3 text-sm ' + (mine ? 'border-xuanor-gold/40 bg-xuanor-gold/10 text-xuanor-cream' : 'border-white/10 bg-white/[0.03] text-xuanor-cream') + '">'
      + '<div>' + escapeHtml(message.text) + '</div>'
      + (message.text !== message.original_text ? '<div class="mt-2 text-xs text-xuanor-muted">Original: ' + escapeHtml(message.original_text) + '</div>' : '')
      + '</div>'
      + '</article>';
  }

  function appendMessages(messages) {
    const shouldStick = isNearBottom() || !messagesNode.children.length;
    messages.forEach(function (message) {
      messagesNode.insertAdjacentHTML('beforeend', renderMessage(message));
      lastMessageId = Math.max(lastMessageId, Number(message.id || 0));
      if (isPanelOpen() && message.sender_type === 'operator') {
        unreadCount = 0;
      } else if (message.sender_type === 'operator') {
        unreadCount += 1;
      }
    });
    badgeNode.textContent = unreadCount;
    badgeNode.classList.toggle('hidden', unreadCount === 0);
    if (shouldStick) {
      messagesNode.scrollTop = messagesNode.scrollHeight;
    }
  }

  async function ensureSession() {
    const payload = {
      visitor_name: form.elements.visitor_name.value.trim(),
      visitor_email: form.elements.visitor_email.value.trim(),
      language: navigator.language || defaultLanguage,
    };
    const data = await fetchJson(sessionUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify(payload),
    });

    pollInterval = Number(data.poll_interval_ms || pollInterval);
    backgroundPollInterval = Number(data.background_poll_interval_ms || backgroundPollInterval);
    messagesNode.innerHTML = '';
    lastMessageId = 0;
    unreadCount = 0;
    hasSentMessage = Boolean((data.messages || []).length);
    if (data.session?.has_contact_details) {
      setDetailsExpanded(true);
      if (data.session.visitor_name) form.elements.visitor_name.value = data.session.visitor_name;
      if (data.session.visitor_email) form.elements.visitor_email.value = data.session.visitor_email;
    }
    appendMessages(data.messages || []);
    return data;
  }

  function restartPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
    }
    const interval = isPanelOpen() && !document.hidden ? pollInterval : backgroundPollInterval;
    pollTimer = window.setInterval(function () {
      refreshMessages().catch(function () {});
    }, interval);
  }

  async function refreshMessages() {
    if (!initialized) return;
    const data = await fetchJson(messagesUrl + '?after=' + encodeURIComponent(lastMessageId));
    if (data.messages?.length) {
      appendMessages(data.messages);
    }
    if (data.session?.has_contact_details && !detailsFields.classList.contains('hidden')) {
      if (data.session.visitor_name) form.elements.visitor_name.value = data.session.visitor_name;
      if (data.session.visitor_email) form.elements.visitor_email.value = data.session.visitor_email;
    }
  }

  async function markRead() {
    try {
      await fetchJson(readUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken(),
        },
      });
      unreadCount = 0;
      badgeNode.textContent = '0';
      badgeNode.classList.add('hidden');
    } catch (error) {
      showError(error.message);
    }
  }

  function openPanel() {
    panel.classList.remove('hidden');
    toggleButton.classList.add('hidden');
    hideTeaser();
    localStorage.setItem(panelOpenedKey, '1');
    restartPolling();
    markRead();
  }

  function closePanel() {
    panel.classList.add('hidden');
    toggleButton.classList.remove('hidden');
    if (hasSentMessage && !form.elements.visitor_email.value.trim()) {
      setDetailsExpanded(true);
      statusNode.textContent = 'Leave your email if you want us to follow up.';
    }
    restartPolling();
  }

  async function initWidget() {
    if (!initialized) {
      await ensureSession();
      initialized = true;
    }
    restartPolling();
  }

  async function handleOpen() {
    clearError();
    try {
      await initWidget();
      openPanel();
    } catch (error) {
      showError(error.message);
      openPanel();
    }
  }

  toggleButton.addEventListener('click', handleOpen);
  closeButton.addEventListener('click', closePanel);
  dismissTeaserButton.addEventListener('click', function () {
    localStorage.setItem(teaserDismissedKey, '1');
    hideTeaser();
  });
  teaser.addEventListener('click', function (event) {
    if (event.target.closest('[data-role="dismiss-teaser"]')) return;
    handleOpen();
  });
  detailsToggle.addEventListener('click', function () {
    setDetailsExpanded(detailsFields.classList.contains('hidden'));
  });

  form.elements.text.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (isSending) return;

    clearError();
    const text = form.elements.text.value.trim();
    if (!text) return;

    try {
      await initWidget();
      setSendingState(true);
      const data = await fetchJson(sendUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ text: text }),
      });
      hasSentMessage = true;
      appendMessages([data.message]);
      form.elements.text.value = '';
      await markRead();
      if (!form.elements.visitor_email.value.trim()) {
        statusNode.textContent = 'Want a follow-up? Add your email below.';
      }
    } catch (error) {
      if (String(error.message).includes('conversation has ended')) {
        setDetailsExpanded(true);
      }
      showError(error.message);
    } finally {
      setSendingState(false);
    }
  });

  document.addEventListener('visibilitychange', restartPolling);
  maybeShowTeaser();
})();
