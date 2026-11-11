(() => {
  'use strict';

  const notice = document.getElementById('wake-lock-notice');
  const message = document.getElementById('wake-lock-message');
  const activate = document.getElementById('wake-lock-activate');
  if (!notice || !message || !activate) return;

  const manualHint = 'O dispositivo pode exigir configuração manual para manter a tela ativa.';
  const supported = window.isSecureContext && typeof navigator.wakeLock?.request === 'function';
  const showHint = (allowActivation = false) => {
    message.textContent = manualHint;
    activate.hidden = !allowActivation;
    notice.hidden = false;
  };
  if (!supported) {
    showHint();
    return;
  }

  let sentinel = null;
  let pending = false;
  let pageActive = true;
  let timer = null;
  let nextAttempt = 0;
  let recoveryAttempts = 0;
  let activationUsed = false;
  const visible = () => pageActive && document.visibilityState === 'visible';
  const cancelRetry = () => {
    window.clearTimeout(timer);
    timer = null;
  };
  const release = () => {
    cancelRetry();
    const current = sentinel;
    sentinel = null; // Ignore release events caused by our own cleanup.
    if (current && !current.released) {
      current.release().catch(() => {});
    }
  };

  const request = async (fromGesture = false) => {
    if (!visible() || pending || sentinel) return;
    cancelRetry();
    const delay = nextAttempt - Date.now();
    if (!fromGesture && delay > 0) {
      timer = window.setTimeout(() => request(), delay);
      return;
    }
    pending = true;
    nextAttempt = Date.now() + 3000;
    try {
      const acquired = await navigator.wakeLock.request('screen');
      if (!visible()) {
        await acquired.release();
        return;
      }
      sentinel = acquired;
      acquired.addEventListener('release', () => {
        if (sentinel !== acquired) return;
        sentinel = null;
        if (!visible()) return;
        // At most two recoveries per visible session; never poll after rejection.
        if (recoveryAttempts < 2) {
          recoveryAttempts += 1;
          timer = window.setTimeout(() => request(), 3000);
        } else {
          showHint(!activationUsed);
        }
      }, { once: true });
      notice.hidden = true;
      activate.hidden = true;
    } catch (_) {
      if (visible()) showHint(!activationUsed);
    } finally {
      pending = false;
    }
  };

  activate.addEventListener('click', (event) => {
    if (!event.isTrusted || activationUsed || pending || !visible()) return;
    activationUsed = true;
    activate.hidden = true;
    // Call directly during the gesture, without a timer or an intervening await.
    request(true);
  });
  document.addEventListener('visibilitychange', () => {
    if (visible()) {
      recoveryAttempts = 0;
      request();
    } else {
      release();
    }
  });
  window.addEventListener('pagehide', () => {
    pageActive = false;
    release();
  });
  window.addEventListener('pageshow', () => {
    pageActive = true;
    request();
  });
  request();
})();
