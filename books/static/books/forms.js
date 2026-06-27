(function () {
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-dismiss-notice]');
    if (!btn) return;
    var notice = btn.closest('[data-dismissible-notice]');
    if (notice) notice.remove();
  });

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-password-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var inputId = btn.getAttribute('aria-controls');
        var input = document.getElementById(inputId);
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
        btn.textContent = show ? 'Hide' : 'Show';
      });
    });

    document.querySelectorAll('[data-secret-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var inputId = btn.getAttribute('aria-controls');
        var input = document.getElementById(inputId);
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
        btn.setAttribute('aria-label', show ? 'Hide value' : 'Show value');
        var showIcon = btn.querySelector('.secret-icon-show');
        var hideIcon = btn.querySelector('.secret-icon-hide');
        if (showIcon) showIcon.classList.toggle('hidden', show);
        if (hideIcon) hideIcon.classList.toggle('hidden', !show);
      });
    });

    document.querySelectorAll('#mobile-drawer a').forEach(function (link) {
      link.addEventListener('click', function () {
        if (window.innerWidth < 1024) closeDrawer();
      });
    });

    document.body.addEventListener('change', function (e) {
      if (e.target && e.target.name === 'status' && e.target.type === 'radio') {
        var details = document.getElementById('reading-progress-details');
        if (details) details.open = e.target.value === 'reading';
      }
    });
  });
})();
