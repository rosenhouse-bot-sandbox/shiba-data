const meta = document.querySelector('meta[name="color-scheme"]');
const KEY = "color-scheme";
const SYSTEM = "light dark";

function show(scheme) {
  meta.content = scheme;
  for (const radio of document.querySelectorAll('#appearance-menu input')) radio.checked = radio.value === scheme;
}

export function initAppearance() {
  show(meta.content);
  document.querySelector("#appearance-menu").addEventListener("change", (e) => {
    const scheme = e.target.value;
    try {
      if (scheme === SYSTEM) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, scheme);
    } catch {}
    show(scheme);
  });
  addEventListener("storage", (e) => {
    if (e.key === KEY || e.key === null) show(e.newValue ?? SYSTEM);
  });
  const button = document.querySelector("#appearance");
  document.querySelector("#appearance-menu").addEventListener("beforetoggle", (e) => {
    if (e.newState !== "open") return;
    const r = button.getBoundingClientRect();
    e.target.style.top = `${r.bottom + 4}px`;
    e.target.style.right = `${document.documentElement.clientWidth - r.right}px`;
  });
}
