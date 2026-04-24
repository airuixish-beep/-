(function () {
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

  function buildWebSocketUrl(path) {
    if (!path) return null;
    if (/^wss?:\/\//.test(path)) return path;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return protocol + '//' + window.location.host + path;
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : null;
    if (!response.ok) {
      throw new Error((data && data.error) || 'Request failed');
    }
    return data || {};
  }

  function callHook(hook) {
    if (typeof hook === 'function') {
      hook.apply(null, Array.prototype.slice.call(arguments, 1));
    }
  }

  function createChatClient(root, options) {
    const config = options || {};
    const form = root.querySelector('[data-role="form"]');
    const messagesNode = root.querySelector('[data-role="messages"]');
    const errorNode = root.querySelector('[data-role="error"]');
    const submitButton = root.querySelector('[data-role="submit"]');
    const statusNode = root.querySelector('[data-role="status"]');
    const sessionUrl = root.dataset.sessionUrl;
    const messagesUrl = root.dataset.messagesUrl;
    const sendUrl = root.dataset.sendUrl;
    const readUrl = root.dataset.readUrl;
    const offlineUrl = root.dataset.offlineUrl;
    const defaultLanguage = root.dataset.defaultLanguage || 'en';
    const initialStatusText = root.dataset.initialStatus || 'Usually replies within a few hours.';
    const sendingStatusText = root.dataset.sendingStatus || 'Sending your message…';
    const sentWithoutEmailStatusText = root.dataset.sentWithoutEmailStatus || 'Want a follow-up? Add your email below.';
    const offlineStatusText = root.dataset.offlineStatus || 'Please leave your contact detail so we can follow up.';
    const composerField = form.elements.text;
    const contactNameField = form.elements.visitor_name;
    const contactEmailField = form.elements.visitor_email;
    const orderField = form.elements.related_order_no;
    const draftStorageKey = (root.id || 'support-chat') + ':draft';

    let initialized = false;
    let pollInterval = 3000;
    let backgroundPollInterval = 9000;
    let pollTimer = null;
    let reconnectTimer = null;
    let realtimeEnabled = false;
    let websocketUrl = null;
    let socket = null;
    let suppressReconnect = false;
    let lastMessageId = 0;
    let unreadCount = 0;
    let isSending = false;
    let hasSentMessage = false;
    let pendingMessages = [];

    function isNearBottom() {
      return messagesNode.scrollHeight - messagesNode.scrollTop - messagesNode.clientHeight < 80;
    }

    function syncUnreadCount() {
      callHook(config.onUnreadChange, unreadCount);
    }

    function setStatus(text) {
      if (statusNode) {
        statusNode.textContent = text;
      }
    }

    function setSendingState(sending) {
      isSending = sending;
      submitButton.disabled = sending;
      submitButton.textContent = sending
        ? (config.sendingButtonText || 'Sending...')
        : (config.submitButtonText || submitButton.dataset.idleLabel || submitButton.textContent);
      setStatus(sending ? sendingStatusText : initialStatusText);
    }

    function showError(message) {
      if (!errorNode) return;
      errorNode.textContent = message;
      errorNode.classList.remove('hidden');
    }

    function clearError() {
      if (!errorNode) return;
      errorNode.textContent = '';
      errorNode.classList.add('hidden');
    }

    function getContactPayload() {
      return {
        visitor_name: contactNameField ? contactNameField.value.trim() : '',
        visitor_email: contactEmailField ? contactEmailField.value.trim() : '',
        related_order_no: orderField ? orderField.value.trim() : '',
      };
    }

    function saveDraft() {
      try {
        window.localStorage.setItem(draftStorageKey, composerField.value || '');
      } catch (error) {}
    }

    function restoreDraft() {
      try {
        const saved = window.localStorage.getItem(draftStorageKey);
        if (saved && !composerField.value) {
          composerField.value = saved;
        }
      } catch (error) {}
    }

    function clearDraft() {
      try {
        window.localStorage.removeItem(draftStorageKey);
      } catch (error) {}
    }

    function syncContactFields(session) {
      if (session.visitor_name && contactNameField) {
        contactNameField.value = session.visitor_name;
      }
      if (session.visitor_email && contactEmailField) {
        contactEmailField.value = session.visitor_email;
      }
      if (session.related_order_no && orderField) {
        orderField.value = session.related_order_no;
      }
    }

    function messageNodeSelector(message) {
      if (message.id) {
        return '[data-message-id="' + String(message.id).replace(/"/g, '\\"') + '"]';
      }
      if (message.client_id) {
        return '[data-client-id="' + String(message.client_id).replace(/"/g, '\\"') + '"]';
      }
      return null;
    }

    function renderMessage(message) {
      const mine = message.sender_type === 'visitor';
      const stateText = message.send_status === 'failed'
        ? 'Failed to send.'
        : (message.send_status === 'sending' ? 'Sending…' : '');
      const retryButton = message.send_status === 'failed'
        ? '<button type="button" class="mt-2 text-xs underline" data-role="retry-message" data-client-id="' + escapeHtml(message.client_id || '') + '">Retry</button>'
        : '';
      return '<article class="' + (mine ? 'text-right' : 'text-left') + '"' + (message.id ? ' data-message-id="' + escapeHtml(message.id) + '"' : '') + (message.client_id ? ' data-client-id="' + escapeHtml(message.client_id) + '"' : '') + '>'
        + '<div class="inline-block max-w-[85%] rounded-2xl border px-4 py-3 text-sm ' + (mine ? 'border-xuanor-gold/40 bg-xuanor-gold/10 text-xuanor-cream' : 'border-white/10 bg-white/[0.03] text-xuanor-cream') + '">'
        + '<div>' + escapeHtml(message.text) + '</div>'
        + (message.text !== message.original_text ? '<div class="mt-2 text-xs text-xuanor-muted">Original: ' + escapeHtml(message.original_text) + '</div>' : '')
        + (stateText ? '<div class="mt-2 text-xs text-xuanor-muted">' + escapeHtml(stateText) + '</div>' : '')
        + retryButton
        + '</div>'
        + '</article>';
    }

    function normalizeRealtimeMessage(message) {
      return {
        id: message.id,
        sender_type: message.sender_type,
        text: message.text_for_visitor || message.original_text,
        original_text: message.original_text,
        original_language: message.original_language,
        translation_status: message.translation_status,
        created_at: message.created_at,
        send_status: 'sent',
      };
    }

    function upsertMessage(message) {
      const selector = messageNodeSelector(message);
      const shouldStick = isNearBottom() || !messagesNode.children.length;
      if (selector) {
        const existingNode = messagesNode.querySelector(selector);
        if (existingNode) {
          existingNode.outerHTML = renderMessage(message);
        } else {
          messagesNode.insertAdjacentHTML('beforeend', renderMessage(message));
        }
      } else {
        messagesNode.insertAdjacentHTML('beforeend', renderMessage(message));
      }
      lastMessageId = Math.max(lastMessageId, Number(message.id || 0));
      if (message.sender_type === 'operator' && message.send_status !== 'sending' && !selector) {
        unreadCount += 1;
      }
      syncUnreadCount();
      if (shouldStick) {
        messagesNode.scrollTop = messagesNode.scrollHeight;
      }
    }

    function appendMessages(messages) {
      messages.forEach(function (message) {
        upsertMessage(message);
      });
    }

    function renderInitialPlaceholder() {
      const placeholder = messagesNode.querySelector('[data-role="initial-message"]');
      messagesNode.innerHTML = placeholder ? placeholder.outerHTML : '';
      lastMessageId = 0;
      unreadCount = 0;
      pendingMessages = [];
      syncUnreadCount();
    }

    function getPendingMessage(clientId) {
      return pendingMessages.find(function (item) {
        return item.client_id === clientId;
      });
    }

    function addPendingMessage(text) {
      const pendingMessage = {
        client_id: 'local-' + Date.now() + '-' + Math.random().toString(16).slice(2),
        sender_type: 'visitor',
        text: text,
        original_text: text,
        send_status: 'sending',
      };
      pendingMessages.push(pendingMessage);
      upsertMessage(pendingMessage);
      return pendingMessage;
    }

    function markPendingFailed(clientId) {
      const pending = getPendingMessage(clientId);
      if (!pending) return;
      pending.send_status = 'failed';
      upsertMessage(pending);
    }

    function clearPending(clientId) {
      pendingMessages = pendingMessages.filter(function (item) {
        return item.client_id !== clientId;
      });
    }

    async function ensureSession() {
      const payload = Object.assign(getContactPayload(), {
        language: navigator.language || defaultLanguage,
      });
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
      realtimeEnabled = Boolean(data.realtime_enabled);
      websocketUrl = buildWebSocketUrl(data.visitor_websocket_url || root.dataset.websocketUrl || '');
      hasSentMessage = Boolean((data.messages || []).length);
      renderInitialPlaceholder();
      syncContactFields(data.session || {});
      callHook(config.onSession, data.session || {});
      appendMessages(data.messages || []);
      restoreDraft();
      return data;
    }

    function closeSocket() {
      suppressReconnect = true;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (socket) {
        socket.close();
        socket = null;
      }
    }

    function scheduleReconnect() {
      if (!realtimeEnabled || suppressReconnect || reconnectTimer) return;
      reconnectTimer = window.setTimeout(function () {
        reconnectTimer = null;
        connectRealtime();
      }, 2000);
    }

    function handleRealtimePayload(payload) {
      if (!payload || !payload.event) return;
      if (payload.event === 'chat.message.created' && payload.message) {
        appendMessages([normalizeRealtimeMessage(payload.message)]);
        if (!document.hidden) {
          markRead().catch(function () {});
        }
      } else if (payload.event === 'chat.session.closed') {
        submitButton.disabled = true;
        setStatus('This conversation has ended. Leave your email and we will follow up.');
      } else if (payload.event === 'chat.session.updated') {
        callHook(config.onSession, payload.session || {});
      }
    }

    function connectRealtime() {
      if (!realtimeEnabled || !websocketUrl || socket) return;
      suppressReconnect = false;
      try {
        socket = new window.WebSocket(websocketUrl);
      } catch (error) {
        socket = null;
        scheduleReconnect();
        return;
      }
      socket.addEventListener('open', function () {
        restartPolling();
      });
      socket.addEventListener('message', function (event) {
        try {
          handleRealtimePayload(JSON.parse(event.data));
        } catch (error) {}
      });
      socket.addEventListener('close', function () {
        socket = null;
        scheduleReconnect();
      });
      socket.addEventListener('error', function () {
        if (socket) {
          socket.close();
        }
      });
    }

    function restartPolling() {
      if (pollTimer) {
        window.clearInterval(pollTimer);
      }
      const interval = (realtimeEnabled && socket && socket.readyState === window.WebSocket.OPEN)
        ? Math.max(backgroundPollInterval, 30000)
        : (typeof config.getPollInterval === 'function'
          ? config.getPollInterval({ pollInterval: pollInterval, backgroundPollInterval: backgroundPollInterval })
          : (!document.hidden ? pollInterval : backgroundPollInterval));
      pollTimer = window.setInterval(function () {
        refreshMessages().catch(function () {});
      }, interval);
    }

    async function refreshMessages() {
      if (!initialized) return;
      const data = await fetchJson(messagesUrl + '?after=' + encodeURIComponent(lastMessageId));
      if (data.messages?.length) {
        appendMessages(data.messages.map(function (message) {
          return Object.assign({}, message, { send_status: 'sent' });
        }));
      }
      callHook(config.onRefresh, data);
      syncContactFields(data.session || {});
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
        syncUnreadCount();
        if (socket && socket.readyState === window.WebSocket.OPEN) {
          socket.send(JSON.stringify({ event: 'chat.mark_read' }));
        }
      } catch (error) {
        showError(error.message);
      }
    }

    async function init() {
      if (initialized) return;
      await ensureSession();
      initialized = true;
      restartPolling();
      connectRealtime();
    }

    async function sendMessage(existingClientId) {
      if (isSending) return;
      clearError();
      const retryPending = existingClientId ? getPendingMessage(existingClientId) : null;
      const text = retryPending ? retryPending.text : composerField.value.trim();
      if (!text) return;

      let nextStatusText = initialStatusText;
      await init();
      setSendingState(true);
      const pendingMessage = retryPending || addPendingMessage(text);
      try {
        const data = await fetchJson(sendUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify(Object.assign(getContactPayload(), {
            text: text,
            language: navigator.language || defaultLanguage,
          })),
        });
        hasSentMessage = true;
        clearPending(pendingMessage.client_id);
        upsertMessage(Object.assign({}, data.message, { client_id: pendingMessage.client_id, send_status: 'sent' }));
        syncContactFields(data.session || {});
        composerField.value = '';
        clearDraft();
        if (!(contactEmailField && contactEmailField.value.trim())) {
          nextStatusText = sentWithoutEmailStatusText;
        }
        callHook(config.onSend, data.message, data.session || {});
      } catch (error) {
        markPendingFailed(pendingMessage.client_id);
        showError(error.message);
        throw error;
      } finally {
        setSendingState(false);
        setStatus(nextStatusText);
      }
    }

    async function submitOfflineMessage() {
      if (isSending || !offlineUrl) return;
      clearError();
      const text = composerField.value.trim();
      const payload = getContactPayload();
      if (!text) {
        showError('请先填写留言内容。');
        return;
      }
      if (!payload.visitor_email) {
        showError('请至少留下邮箱或其他联系方式。');
        return;
      }
      setSendingState(true);
      try {
        await fetchJson(offlineUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
          },
          body: JSON.stringify({
            name: payload.visitor_name,
            contact: payload.visitor_email,
            related_order_no: payload.related_order_no,
            message: text,
          }),
        });
        composerField.value = '';
        clearDraft();
        setStatus(offlineStatusText);
        callHook(config.onOfflineSubmitted, payload);
      } catch (error) {
        showError(error.message);
      } finally {
        setSendingState(false);
      }
    }

    function bindComposer() {
      submitButton.dataset.idleLabel = submitButton.textContent;
      composerField.addEventListener('input', saveDraft);

      composerField.addEventListener('keydown', function (event) {
        const shouldSubmit = typeof config.shouldSubmitOnKeydown === 'function'
          ? config.shouldSubmitOnKeydown(event)
          : (event.key === 'Enter' && !event.shiftKey);
        if (!shouldSubmit) return;
        event.preventDefault();
        form.requestSubmit();
      });

      form.addEventListener('submit', async function (event) {
        event.preventDefault();
        try {
          await sendMessage();
          callHook(config.afterSubmit);
        } catch (error) {
          callHook(config.onSendError, error);
        }
      });

      messagesNode.addEventListener('click', function (event) {
        const retryButton = event.target.closest('[data-role="retry-message"]');
        if (!retryButton) return;
        sendMessage(retryButton.dataset.clientId).catch(function () {});
      });

      const offlineButton = root.querySelector('[data-role="offline-submit"]');
      if (offlineButton) {
        offlineButton.addEventListener('click', function () {
          submitOfflineMessage().catch(function () {});
        });
      }
    }

    bindComposer();

    return {
      init: init,
      ensureSession: ensureSession,
      refreshMessages: refreshMessages,
      markRead: markRead,
      restartPolling: restartPolling,
      connectRealtime: connectRealtime,
      closeRealtime: closeSocket,
      clearError: clearError,
      showError: showError,
      getHasSentMessage: function () {
        return hasSentMessage;
      },
      getForm: function () {
        return form;
      },
      getStatusNode: function () {
        return statusNode;
      },
      isInitialized: function () {
        return initialized;
      },
      isSending: function () {
        return isSending;
      },
      setUnreadCount: function (count) {
        unreadCount = count;
        syncUnreadCount();
      },
    };
  }

  window.SupportChat = {
    createChatClient: createChatClient,
  };
})();
