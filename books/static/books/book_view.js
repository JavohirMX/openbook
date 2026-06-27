(function () {
  const STORAGE_KEY = "openbook-book-view";
  const VIEWS = ["list", "grid", "compact", "table"];

  function getBookView() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return VIEWS.includes(stored) ? stored : "list";
  }

  function updateToggleUI(view) {
    document.querySelectorAll("[data-book-view-option]").forEach((btn) => {
      const active = btn.getAttribute("data-book-view-option") === view;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.classList.toggle("bg-neutral-100", active);
      btn.classList.toggle("text-neutral-950", active);
      btn.classList.toggle("dark:bg-neutral-800", active);
      btn.classList.toggle("dark:text-neutral-100", active);
    });
  }

  function syncHiddenInput(view) {
    const input = document.getElementById("book-view-input");
    if (input) {
      input.value = view;
    }
    const bulkInput = document.getElementById("bulk-view-input");
    if (bulkInput) {
      bulkInput.value = view;
    }
  }

  function applyBookView(view) {
    updateToggleUI(view);
    syncHiddenInput(view);
  }

  function setBookView(view, options) {
    options = options || {};
    if (!VIEWS.includes(view)) {
      return;
    }
    localStorage.setItem(STORAGE_KEY, view);
    applyBookView(view);

    const url = new URL(window.location.href);
    url.searchParams.set("view", view);

    if (options.htmx) {
      history.replaceState({}, "", url);
      const viewInput = document.getElementById("book-view-input");
      if (viewInput && typeof htmx !== "undefined") {
        htmx.trigger(viewInput, "change");
      }
      const live = document.getElementById("htmx-live-region");
      if (live) {
        live.textContent = "Layout updated.";
      }
    } else {
      window.location.href = url.toString();
    }

    window.dispatchEvent(
      new CustomEvent("bookviewchange", {
        detail: { view: view },
      })
    );
  }

  (function syncFromStorage() {
    if (!document.querySelector("[data-book-view-page]")) {
      return;
    }
    const url = new URL(window.location.href);
    if (url.searchParams.has("view")) {
      return;
    }
    const stored = getBookView();
    if (stored === "list") {
      return;
    }
    url.searchParams.set("view", stored);
    window.location.replace(url.toString());
  })();

  document.addEventListener("DOMContentLoaded", function () {
    const urlView = new URLSearchParams(window.location.search).get("view");
    const view = VIEWS.includes(urlView) ? urlView : getBookView();
    if (urlView && VIEWS.includes(urlView)) {
      localStorage.setItem(STORAGE_KEY, urlView);
    }
    applyBookView(view);

    document.querySelectorAll("[data-book-view-option]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const next = btn.getAttribute("data-book-view-option");
        const htmx = !!document.getElementById("book-filter-form");
        setBookView(next, { htmx: htmx });
      });
    });
  });

  window.openbookBookView = {
    getBookView: getBookView,
    setBookView: setBookView,
    applyBookView: applyBookView,
  };
})();
