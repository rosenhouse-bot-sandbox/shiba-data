// Finds a quote in a page's text items, ignoring whitespace and case.
// The quote comes from pdfium and the items from pdf.js, which can order table text differently.
// When the whole quote is absent, the longest runs of at least MIN_WORDS words are matched instead.
const MIN_WORDS = 3;

function index(items) {
  let text = "";
  const pos = [];
  items.forEach((s, item) => {
    for (let i = 0; i < s.length; i++) {
      if (/\s/.test(s[i])) continue;
      text += s[i].toLowerCase();
      pos.push({ item, offset: i });
    }
  });
  return { text, pos };
}

const squash = (s) => s.replace(/\s+/g, "").toLowerCase();

export function matchRanges(items, quote) {
  const page = index(items);
  const hits = [];
  const whole = page.text.indexOf(squash(quote));
  if (whole >= 0 && quote.trim()) {
    hits.push([whole, whole + squash(quote).length]);
  } else {
    const words = quote.split(/\s+/).filter(Boolean);
    let i = 0;
    while (i < words.length) {
      let best = null;
      for (let j = words.length; j >= i + MIN_WORDS; j--) {
        const at = page.text.indexOf(squash(words.slice(i, j).join("")));
        if (at >= 0) {
          best = { at, len: squash(words.slice(i, j).join("")).length, next: j };
          break;
        }
      }
      if (best) {
        hits.push([best.at, best.at + best.len]);
        i = best.next;
      } else {
        i++;
      }
    }
  }

  const ranges = new Map();
  for (const [from, to] of hits) {
    for (let k = from; k < to; k++) {
      const { item, offset } = page.pos[k];
      const r = ranges.get(item);
      if (!r) ranges.set(item, { item, start: offset, end: offset + 1 });
      else {
        r.start = Math.min(r.start, offset);
        r.end = Math.max(r.end, offset + 1);
      }
    }
  }
  return [...ranges.values()].sort((a, b) => a.item - b.item);
}
