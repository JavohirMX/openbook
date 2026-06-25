(function () {
  const STORAGE_KEY = "openbook-theme";
  const THEMES = ["light", "dark", "system"];

  function getTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(stored) ? stored : "light";
  }

  function isDark(theme) {
    if (theme === "dark") return true;
    if (theme === "light") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function updatePickerUI(theme) {
    document.querySelectorAll("[data-theme-option]").forEach((btn) => {
      const active = btn.getAttribute("data-theme-option") === theme;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.classList.toggle("bg-neutral-100", active);
      btn.classList.toggle("text-neutral-950", active);
      btn.classList.toggle("dark:bg-neutral-800", active);
      btn.classList.toggle("dark:text-neutral-100", active);
    });
  }

  function applyTheme() {
    const theme = getTheme();
    document.documentElement.classList.toggle("dark", isDark(theme));
    updatePickerUI(theme);
    window.dispatchEvent(
      new CustomEvent("themechange", {
        detail: { theme, isDark: isDark(theme) },
      })
    );
  }

  function setTheme(theme) {
    if (!THEMES.includes(theme)) return;
    localStorage.setItem(STORAGE_KEY, theme);
    applyTheme();
  }

  let mediaQuery = null;
  function setupSystemListener() {
    if (mediaQuery) return;
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener("change", () => {
      if (getTheme() === "system") applyTheme();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupSystemListener();
    applyTheme();
    document.querySelectorAll("[data-theme-option]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setTheme(btn.getAttribute("data-theme-option"));
      });
    });
  });

  window.openbookTheme = {
    getTheme,
    setTheme,
    applyTheme,
    isDark: () => isDark(getTheme()),
  };
})();
