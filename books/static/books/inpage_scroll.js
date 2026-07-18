(function () {
  var stickyRestoreListening = false;

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function mainEl() {
    return document.getElementById('main-content');
  }

  function resolveTarget(hash) {
    if (!hash || hash === '#') return null;
    var id = decodeURIComponent(hash.slice(1));
    if (!id || id === 'main-content') return null;
    var main = mainEl();
    if (!main) return null;
    var el = null;
    try {
      el = document.getElementById(id);
    } catch (e) {
      return null;
    }
    if (!el || !main.contains(el)) return null;
    return el;
  }

  function scrollMarginTop(el) {
    var value = parseFloat(window.getComputedStyle(el).scrollMarginTop);
    return isNaN(value) ? 0 : value;
  }

  function targetScrollTop(main, target) {
    var mainRect = main.getBoundingClientRect();
    var targetRect = target.getBoundingClientRect();
    return main.scrollTop + (targetRect.top - mainRect.top) - scrollMarginTop(target);
  }

  function maxScrollTop(main) {
    return Math.max(0, main.scrollHeight - main.clientHeight);
  }

  function setStickyEnabled(enabled) {
    var nodes = document.querySelectorAll('[data-inpage-sticky]');
    for (var i = 0; i < nodes.length; i++) {
      if (enabled) {
        nodes[i].style.removeProperty('position');
        nodes[i].style.removeProperty('top');
      } else {
        // Sticky inside an overflow scroller can inflate scrollHeight (blank gap).
        nodes[i].style.position = 'relative';
        nodes[i].style.top = 'auto';
      }
    }
  }

  function watchStickyRestore(main) {
    if (stickyRestoreListening) return;
    stickyRestoreListening = true;
    function onScroll() {
      if (main.scrollTop <= 8) {
        setStickyEnabled(true);
        main.removeEventListener('scroll', onScroll);
        stickyRestoreListening = false;
      }
    }
    main.addEventListener('scroll', onScroll, { passive: true });
  }

  function animateMainScroll(main, toTop, duration, done) {
    var fromTop = main.scrollTop;
    var delta = toTop - fromTop;
    if (!delta || duration <= 0) {
      main.scrollTop = toTop;
      if (done) done();
      return;
    }
    var start = null;
    function frame(ts) {
      if (start === null) start = ts;
      var t = Math.min(1, (ts - start) / duration);
      var eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      main.scrollTop = fromTop + delta * eased;
      if (t < 1) {
        window.requestAnimationFrame(frame);
      } else if (done) {
        done();
      }
    }
    window.requestAnimationFrame(frame);
  }

  function scrollMainTo(target, smooth) {
    var main = mainEl();
    if (!main) return;

    setStickyEnabled(false);
    void main.offsetHeight;

    var top = Math.min(Math.max(0, targetScrollTop(main, target)), maxScrollTop(main));
    var finish = function () {
      main.scrollTop = Math.min(main.scrollTop, maxScrollTop(main));
      watchStickyRestore(main);
    };

    if (smooth && !prefersReducedMotion()) {
      animateMainScroll(main, top, 420, finish);
    } else {
      main.scrollTop = top;
      finish();
    }
  }

  function hashUrl(hash) {
    return window.location.pathname + window.location.search + hash;
  }

  function scrollToHash(hash, updateHistory, smooth) {
    var target = resolveTarget(hash);
    if (!target) return false;
    scrollMainTo(target, smooth !== false);
    if (updateHistory && window.location.hash !== hash) {
      history.pushState(null, '', hashUrl(hash));
    }
    return true;
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('a[href^="#"]');
    if (!link) return;
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      return;
    }
    var href = link.getAttribute('href');
    if (!resolveTarget(href)) return;
    e.preventDefault();
    scrollToHash(href, true, true);
  });

  function scrollFromLocation() {
    if (!window.location.hash) return;
    scrollToHash(window.location.hash, false, false);
  }

  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
  }

  window.addEventListener('popstate', scrollFromLocation);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scrollFromLocation);
  } else {
    scrollFromLocation();
  }
})();
