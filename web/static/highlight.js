// Finds a quote in a page's text items, ignoring whitespace and case.
// Returns one character range per item that the quote touches, or nothing if the whole quote is absent.
const squash = (s) => s.replace(/\s+/g, "").toLowerCase();

export function matchRanges(items, quote) {
  let text = "";
  const pos = [];
  items.forEach((s, item) => {
    for (let i = 0; i < s.length; i++) {
      if (/\s/.test(s[i])) continue;
      text += s[i].toLowerCase();
      pos.push({ item, offset: i });
    }
  });
  const needle = squash(quote);
  const at = needle ? text.indexOf(needle) : -1;
  if (at < 0) return [];

  const ranges = new Map();
  for (const { item, offset } of pos.slice(at, at + needle.length)) {
    const r = ranges.get(item);
    if (r) r.end = offset + 1;
    else ranges.set(item, { item, start: offset, end: offset + 1 });
  }
  return [...ranges.values()];
}
