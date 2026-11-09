const SVG = "http://www.w3.org/2000/svg";

function build(e, attrs, kids) {
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.setAttribute("class", v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  e.append(...kids.filter((k) => k != null));
  return e;
}

export const el = (tag, attrs = {}, ...kids) => build(document.createElement(tag), attrs, kids);
export const svg = (tag, attrs = {}, ...kids) => build(document.createElementNS(SVG, tag), attrs, kids);
