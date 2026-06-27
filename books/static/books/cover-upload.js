(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var fileInput = document.getElementById('id_cover_image');
    var preview = document.getElementById('cover-preview');
    var current = document.getElementById('cover-current');
    var removeCheckbox = document.getElementById('id_remove_cover');
    var previewObjectUrl = null;

    if (!fileInput || !preview) return;

    function revokePreviewUrl() {
      if (previewObjectUrl) {
        URL.revokeObjectURL(previewObjectUrl);
        previewObjectUrl = null;
      }
    }

    fileInput.addEventListener('change', function () {
      revokePreviewUrl();
      var file = fileInput.files && fileInput.files[0];
      if (!file) {
        preview.classList.add('hidden');
        preview.removeAttribute('src');
        return;
      }
      previewObjectUrl = URL.createObjectURL(file);
      preview.src = previewObjectUrl;
      preview.classList.remove('hidden');
      if (removeCheckbox) {
        removeCheckbox.checked = false;
      }
    });

    if (removeCheckbox) {
      removeCheckbox.addEventListener('change', function () {
        if (removeCheckbox.checked) {
          fileInput.value = '';
          revokePreviewUrl();
          preview.classList.add('hidden');
          preview.removeAttribute('src');
        }
      });
    }
  });
})();
