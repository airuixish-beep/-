(function () {
  const root = document.getElementById('support-chat-page');
  if (!root || !window.SupportChat) return;

  const quickFillButtons = document.querySelectorAll('[data-role="quick-fill"]');
  const client = window.SupportChat.createChatClient(root, {
    sendingButtonText: '发送中...',
    submitButtonText: '发送消息',
    getPollInterval: function (intervals) {
      return document.hidden ? intervals.backgroundPollInterval : intervals.pollInterval;
    },
    afterSubmit: function () {
      client.markRead();
    },
  });

  function bindQuickFill() {
    const form = client.getForm();
    const textField = form.elements.text;
    quickFillButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        const prompt = button.dataset.prompt || '';
        textField.value = prompt;
        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(function () {
          textField.focus();
          textField.setSelectionRange(textField.value.length, textField.value.length);
        }, 180);
      });
    });
  }

  async function start() {
    client.clearError();
    try {
      await client.init();
      await client.markRead();
    } catch (error) {
      client.showError(error.message);
    }
  }

  document.addEventListener('visibilitychange', function () {
    client.restartPolling();
    if (!document.hidden) {
      client.markRead();
    }
  });

  bindQuickFill();
  start();
})();
