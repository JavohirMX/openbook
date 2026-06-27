(function () {
  const STORAGE_KEY = "openbook-book-sort";
  const DEFAULT_SORT = "-created_at";
  const VALID_SORTS = ["-created_at", "title", "-title", "author", "-finished_at"];

  function getBookSort() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return VALID_SORTS.includes(stored) ? stored : DEFAULT_SORT;
  }

  (function syncFromStorage() {
    if (!document.querySelector("[data-book-sort-page]")) {
      return;
    }
    const url = new URL(window.location.href);
    if (url.searchParams.has("sort")) {
      return;
    }
    const stored = getBookSort();
    if (stored === DEFAULT_SORT) {
      return;
    }
    url.searchParams.set("sort", stored);
    window.location.replace(url.toString());
  })();

  document.addEventListener("DOMContentLoaded", function () {
    const urlSort = new URLSearchParams(window.location.search).get("sort");
    if (urlSort && VALID_SORTS.includes(urlSort)) {
      localStorage.setItem(STORAGE_KEY, urlSort);
    }

    document.querySelectorAll("[data-book-sort-select]").forEach(function (select) {
      select.addEventListener("change", function () {
        const sort = select.value;
        if (!VALID_SORTS.includes(sort)) {
          return;
        }
        localStorage.setItem(STORAGE_KEY, sort);
        const url = new URL(window.location.href);
        url.searchParams.set("sort", sort);
        window.location.href = url.toString();
      });
    });

    const filterSort = document.getElementById("filter-sort");
    if (filterSort) {
      filterSort.addEventListener("change", function () {
        if (VALID_SORTS.includes(filterSort.value)) {
          localStorage.setItem(STORAGE_KEY, filterSort.value);
        }
      });
    }
  });
})();
