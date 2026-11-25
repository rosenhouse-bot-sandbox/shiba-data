// Runs before the page draws, so a saved choice shows no flash of the other scheme.
try {
  const saved = localStorage.getItem("color-scheme");
  if (saved === "light" || saved === "dark") document.querySelector('meta[name="color-scheme"]').content = saved;
} catch {}
