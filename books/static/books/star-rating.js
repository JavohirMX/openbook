(function () {
  function starSvg(filled) {
    return filled
      ? '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z"/></svg>'
      : '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z"/></svg>';
  }

  function setRating(container, value) {
    var input = document.getElementById(container.getAttribute('data-rating-input'));
    if (input) input.value = value;
    container.querySelectorAll('[data-star]').forEach(function (btn) {
      var star = parseInt(btn.getAttribute('data-star'), 10);
      var filled = star <= value;
      btn.classList.toggle('is-filled', filled);
      btn.innerHTML = starSvg(filled);
      btn.setAttribute('aria-pressed', filled ? 'true' : 'false');
    });
    var summary = document.getElementById(container.getAttribute('data-rating-summary'));
    if (summary) {
      summary.textContent = value ? 'My rating: ' + value + ' / 5' : 'No rating yet';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-star-rating]').forEach(function (container) {
      var input = document.getElementById(container.getAttribute('data-rating-input'));
      var initial = input ? parseInt(input.value, 10) || 0 : 0;
      setRating(container, initial);

      container.querySelectorAll('[data-star]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          setRating(container, parseInt(btn.getAttribute('data-star'), 10));
        });
      });
    });
  });
})();
