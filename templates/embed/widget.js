(function () {
  var payload = {{ payload_json|safe }};
  var target = document.currentScript && document.currentScript.previousElementSibling;
  if (!target || !payload) return;

  var html = '<div class="openbook-embed" style="font-family:system-ui,sans-serif;max-width:320px">';
  html += '<p style="font-weight:600;margin:0 0 8px;font-size:14px">' + (payload.title || 'Reading') + '</p>';
  if (!payload.books || !payload.books.length) {
    html += '<p style="margin:0;font-size:13px;color:#666">Nothing to show.</p>';
  } else {
    html += '<ul style="list-style:none;margin:0;padding:0">';
    payload.books.forEach(function (book) {
      html += '<li style="display:flex;gap:10px;margin-bottom:10px;align-items:flex-start">';
      if (book.cover_url) {
        html += '<img src="' + book.cover_url + '" alt="" width="40" height="60" style="object-fit:cover;border-radius:2px" />';
      }
      html += '<div><span style="font-size:13px;font-weight:500;display:block">' + book.title + '</span>';
      if (book.authors && book.authors.length) {
        html += '<span style="font-size:12px;color:#666">' + book.authors.join(', ') + '</span>';
      }
      if (book.progress_percent != null) {
        html += '<span style="font-size:11px;color:#888;display:block">' + book.progress_percent + '%</span>';
      }
      html += '</div></li>';
    });
    html += '</ul>';
  }
  html += '<p style="margin:8px 0 0;font-size:11px;color:#999">via openbook</p></div>';
  target.innerHTML = html;
})();
