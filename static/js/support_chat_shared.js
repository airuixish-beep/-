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

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Request failed');
    }
    return data;
  }

  function createChatClient(root, options) {
    const form = root.querySelector('[data-role="form"]');
    const messagesNode = root.querySelector('[data-role="messages"]');
    const errorNode = root.querySelector('[data-role="error"]');
    const submitButton = root.querySelector('[data-role="submit"]');
    const statusNode = root.querySelector('[data-role="status"]');
    const sessionUrl = root.dataset.sessionUrl;
    const messagesUrl = root.dataset.messagesUrl;
    const sendUrl = root.dataset.sendUrl;
    const readUrl = root.dataset.readUrl;
    const defaultLanguage = root.dataset.defaultLanguage || 'en';
    const initialStatusText = root.dataset.initialStatus || 'Usually replies within a few hours.';
    const sendingStatusText = root.dataset.sendingStatus || 'Sending your message…';
    const sentWithoutEmailStatusText = root.dataset.sentWithoutEmailStatus || 'Want a follow-up? Add your email below.';

    let initialized = false;
    let pollInterval = 3000;
    let backgroundPollInterval = 9000;
    let pollTimer = null;
    let lastMessageId = 0;
    let unreadCount = 0;
    let isSending = false;
    let hasSentMessage = false;

    function isNearBottom() {
      return messagesNode.scrollHeight - messagesNode.scrollTop - messagesNode.clientHeight < 80;
    }

    function setSendingState(sending) {
      isSending = sending;
      submitButton.disabled = sending;
      submitButton.textContent = sending ? (options.sendingButtonText || 'Sending...') : (options.submitButtonText || submitButton.dataset.idleLabel || submitButton.textContent);
      statusNode.textContent = sending ? sendingStatusText : initialStatusText;
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
        if (message.sender_type === 'operator') {
          unreadCount += 1;
        }
      });
      if (typeof options.onUnreadChange === 'function') {
        options.onUnreadChange(unreadCount);
      }
      if (shouldStick) {
        messagesNode.scrollTop = messagesNode.scrollHeight;
      }
    }

    async function ensureSession() {
      const payload = {
        visitor_name: form.elements.visitor_name?.value.trim() || '',
        visitor_email: form.elements.visitor_email?.value.trim() || '',
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

      if (data.session?.visitor_name && form.elements.visitor_name) {
        form.elements.visitor_name.value = data.session.visitor_name;
      }
      if (data.session?.visitor_email && form.elements.visitor_email) {
        form.elements.visitor_email.value = data.session.visitor_email;
      }
      if (typeof options.onSession === 'function') {
        options.onSession(data.session || {});
      }
      appendMessages(data.messages || []);
      return data;
    }

    function restartPolling() {
      if (pollTimer) {
        window.clearInterval(pollTimer);
      }
      const interval = typeof options.getPollInterval === 'function'
        ? options.getPollInterval({ pollInterval: pollInterval, backgroundPollInterval: backgroundPollInterval })
        : (!document.hidden ? pollInterval : backgroundPollInterval);
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
      if (typeof options.onRefresh === 'function') {
        options.onRefresh(data);
      }
      if (data.session?.visitor_name && form.elements.visitor_name) {
        form.elements.visitor_name.value = data.session.visitor_name;
      }
      if (data.session?.visitor_email && form.elements.visitor_email) {
        form.elements.visitor_email.value = data.session.visitor_email;
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
        if (typeof options.onUnreadChange === 'function') {
          options.onUnreadChange(unreadCount);
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
    }

    async function sendMessage() {
      if (isSending) return;
      clearError();
      const text = form.elements.text.value.trim();
      if (!text) return;

      let nextStatusText = initialStatusText;
      await init();
      setSendingState(true);
      try {
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
        if (!form.elements.visitor_email?.value.trim()) {
          nextStatusText = sentWithoutEmailStatusText;
        }
        if (typeof options.onSend === 'function') {
          options.onSend(data.message);
        }
      } catch (error) {
        showError(error.message);
        throw error;
      } finally {
        setSendingState(false);
        statusNode.textContent = nextStatusText;
      }
    }

    function bindComposer() {
      const textField = form.elements.text;
      const idleLabel = submitButton.textContent;
      submitButton.dataset.idleLabel = idleLabel;

      textField.addEventListener('keydown', function (event) {
        const shouldSubmit = typeof options.shouldSubmitOnKeydown === 'function'
          ? options.shouldSubmitOnKeydown(event)
          : (event.key === 'Enter' && !event.shiftKey);
        if (!shouldSubmit) return;
        event.preventDefault();
        form.requestSubmit();
      });

      form.addEventListener('submit', async function (event) {
        event.preventDefault();
        try {
          await sendMessage();
          if (typeof options.afterSubmit === 'function') {
            options.afterSubmit();
          }
        } catch (error) {
          if (typeof options.onSendError === 'function') {
            options.onSendError(error);
          }
        }
      });
    }

    bindComposer();

    return {
      init: init,
      ensureSession: ensureSession,
      refreshMessages: refreshMessages,
      markRead: markRead,
      restartPolling: restartPolling,
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
        if (typeof options.onUnreadChange === 'function') {
          options.onUnreadChange(unreadCount);
        }
      },
    };
  }

  window.SupportChat = {
    createChatClient: createChatClient,
  };
})();
