const meta = document.querySelector('meta[name="color-scheme"]');
const KEY = "color-scheme";
const SYSTEM = "light dark";

function show(scheme) {
  meta.content = scheme === "light" || scheme === "dark" ? scheme : SYSTEM;
  for (const radio of document.querySelectorAll("#appearance-menu input")) radio.checked = radio.value === meta.content;
}

export function initAppearance() {
  const button = document.querySelector("#appearance");
  const menu = document.querySelector("#appearance-menu");
  show(meta.content);
  menu.addEventListener("change", (e) => {
    const scheme = e.target.value;
    try {
      if (scheme === SYSTEM) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, scheme);
    } catch {}
    show(scheme);
  });
  addEventListener("storage", (e) => {
    if (e.key === KEY || e.key === null) show(e.newValue);
  });
  menu.addEventListener("beforetoggle", (e) => {
    if (e.newState !== "open") return;
    const r = button.getBoundingClientRect();
    menu.style.top = `${r.bottom + 4}px`;
    menu.style.right = `${document.documentElement.clientWidth - r.right}px`;
  });
  addEventListener("resize", () => menu.hidePopover());
}
