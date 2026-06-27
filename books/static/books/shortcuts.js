(function () {
  var pending = null;
  var pendingTimer = null;
  var PENDING_MS = 1000;

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function focusSearch() {
    var input = document.getElementById('global-search')
      || document.getElementById('search-input')
      || document.getElementById('mobile-search');
    if (!input) return;
    if (window.innerWidth < 640) {
      var panel = document.getElementById('mobile-search-panel');
      if (panel) panel.classList.remove('hidden');
    }
    input.focus();
    input.select();
  }

  function clearPending() {
    pending = null;
    if (pendingTimer) {
      clearTimeout(pendingTimer);
      pendingTimer = null;
    }
  }

  function scheduleGo(key, url) {
    clearPending();
    pending = key;
    pendingTimer = setTimeout(function () {
      pending = null;
      pendingTimer = null;
    }, PENDING_MS);
  }

  function navigate(url) {
    if (url) window.location.href = url;
  }

  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    if (isTypingTarget(document.activeElement)) return;

    if (e.key === '/') {
      e.preventDefault();
      clearPending();
      focusSearch();
      return;
    }

    var body = document.body;
    var booksUrl = body.getAttribute('data-books-url');
    var statsUrl = body.getAttribute('data-stats-url');

    if (e.key === 'g') {
      scheduleGo('g');
      return;
    }

    if (pending === 'g') {
      clearPending();
      if (e.key === 'b' && booksUrl) {
        e.preventDefault();
        navigate(booksUrl);
      } else if (e.key === 's' && statsUrl) {
        e.preventDefault();
        navigate(statsUrl);
      }
    }
  });
})();
