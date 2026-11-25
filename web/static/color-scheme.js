// Runs before the page draws, so a saved choice shows no flash of the other scheme.
try {
  document.querySelector('meta[name="color-scheme"]').content = localStorage.getItem("color-scheme") ?? "light dark";
} catch {}
