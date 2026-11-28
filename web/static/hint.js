// A term that shows its pop-over while hovered or focused. Clicking pins it open.
import { el } from "./dom.js";

let pops = 0;
// The one open pop-over, if any.
let opened = null;

const MARGIN = 8;

export function hint(text, ...content) {
  const id = `term-pop-${++pops}`;
  const button = el("button", { type: "button", class: "term", "aria-expanded": "false", "aria-controls": id }, text);
  const pop = el("div", { class: "term-pop", id }, ...content);
  const box = el("span", { class: "term-box" }, button, pop);
  let pinned = false;
  const close = () => {
    pinned = false;
    box.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
    if (opened?.box === box) opened = null;
  };
  const open = () => {
    if (opened?.box !== box) opened?.close();
    opened = { box, close };
    box.classList.add("open");
    button.setAttribute("aria-expanded", "true");
    place(pop, button.getBoundingClientRect());
  };
  const leave = () => pinned || box.contains(document.activeElement) || close();
  box.addEventListener("mouseenter", open);
  box.addEventListener("mouseleave", leave);
  button.addEventListener("focus", open);
  box.addEventListener("focusout", (e) => pinned || box.contains(e.relatedTarget) || close());
  button.addEventListener("click", () => {
    if (pinned) return close();
    open();
    pinned = true;
  });
  return box;
}

// Places a pop-over under its term, or above it when it fits only there or there is more room, and shrinks it to fit.
function place(pop, at) {
  const { innerWidth: w, innerHeight: h } = window;
  pop.style.maxWidth = `${w - 2 * MARGIN}px`;
  const roomBelow = h - MARGIN - at.bottom - 4, roomAbove = at.top - 4 - MARGIN;
  pop.style.maxHeight = "";
  const fitsBelow = pop.getBoundingClientRect().height <= roomBelow;
  const room = fitsBelow || roomBelow >= roomAbove ? roomBelow : roomAbove;
  pop.style.maxHeight = `${room}px`;
  const { width, height } = pop.getBoundingClientRect();
  pop.style.left = `${Math.max(MARGIN, Math.min(at.left, w - width - MARGIN))}px`;
  pop.style.top = `${room === roomBelow ? at.bottom + 4 : at.top - 4 - height}px`;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") opened?.close();
});
document.addEventListener("click", (e) => {
  if (opened && !opened.box.contains(e.target)) opened.close();
});
document.addEventListener("scroll", (e) => opened && !opened.box.contains(e.target) && opened.close(), true);
