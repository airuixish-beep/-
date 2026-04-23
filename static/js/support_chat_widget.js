(function () {
  const root = document.getElementById('support-chat-widget');
  if (!root || !window.SupportChat) return;

  const toggleButton = root.querySelector('[data-role="toggle"]');
  const panel = root.querySelector('[data-role="panel"]');
  const teaser = root.querySelector('[data-role="teaser"]');
  const dismissTeaserButton = root.querySelector('[data-role="dismiss-teaser"]');
  const closeButton = root.querySelector('[data-role="close"]');
  const badgeNode = root.querySelector('[data-role="badge"]');
  const detailsToggle = root.querySelector('[data-role="details-toggle"]');
  const detailsFields = root.querySelector('[data-role="details-fields"]');
  const teaserDelay = Number(root.dataset.teaserDelay || 8000);

  const teaserDismissedKey = 'support-chat-teaser-dismissed';
  const panelOpenedKey = 'support-chat-panel-opened';

  function isPanelOpen() {
    return !panel.classList.contains('hidden');
  }

  function setDetailsExpanded(expanded) {
    detailsFields.classList.toggle('hidden', !expanded);
    detailsToggle.textContent = expanded ? 'Hide contact details' : 'Add your name or email for follow-up';
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

  const client = window.SupportChat.createChatClient(root, {
    sendingButtonText: 'Sending...',
    submitButtonText: 'Send',
    getPollInterval: function (intervals) {
      return isPanelOpen() && !document.hidden ? intervals.pollInterval : intervals.backgroundPollInterval;
    },
    onUnreadChange: function (count) {
      const nextCount = isPanelOpen() ? 0 : count;
      badgeNode.textContent = String(nextCount);
      badgeNode.classList.toggle('hidden', nextCount === 0);
    },
    onSession: function (session) {
      if (session.has_contact_details) {
        setDetailsExpanded(true);
      }
    },
    onRefresh: function () {
      if (isPanelOpen()) {
        client.setUnreadCount(0);
      }
    },
    onSendError: function (error) {
      if (String(error.message).includes('conversation has ended')) {
        setDetailsExpanded(true);
      }
    },
  });

  function openPanel() {
    panel.classList.remove('hidden');
    toggleButton.classList.add('hidden');
    hideTeaser();
    localStorage.setItem(panelOpenedKey, '1');
    client.restartPolling();
    client.markRead();
  }

  function closePanel() {
    panel.classList.add('hidden');
    toggleButton.classList.remove('hidden');
    const form = client.getForm();
    if (client.getHasSentMessage() && !form.elements.visitor_email.value.trim()) {
      setDetailsExpanded(true);
      client.getStatusNode().textContent = 'Leave your email if you want us to follow up.';
    }
    client.restartPolling();
  }

  async function handleOpen() {
    client.clearError();
    try {
      await client.init();
      openPanel();
    } catch (error) {
      client.showError(error.message);
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

  document.addEventListener('visibilitychange', function () {
    client.restartPolling();
  });
  maybeShowTeaser();
})();
