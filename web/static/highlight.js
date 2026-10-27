// Finds a quote in a page's text items, ignoring whitespace and case.
// Returns one character range per item that the quote touches, or nothing if the whole quote is absent.
// Given each item's left edge, a quote may instead run down one column of a table whose columns alternate in
// item order. Such a quote must occur in only one column.
export const squash = (s) => s.replace(/\s+/g, "").toLowerCase();

export function matchRanges(items, quote, lefts = []) {
  const needle = squash(quote);
  if (!needle) return [];
  const [first] = occurrences(items, items.map((s, i) => i), needle);
  if (first) return first;
  const columns = new Map();
  lefts.forEach((x, i) => columns.set(Math.round(x), [...(columns.get(Math.round(x)) ?? []), i]));
  const hits = [...columns.values()].flatMap((order) => occurrences(items, order, needle));
  return hits.length === 1 ? hits[0] : [];
}

function occurrences(items, order, needle) {
  let text = "";
  const pos = [];
  for (const item of order) {
    const s = items[item];
    for (let i = 0; i < s.length; i++) {
      if (/\s/.test(s[i])) continue;
      text += s[i].toLowerCase();
      pos.push({ item, offset: i });
    }
  }
  const found = [];
  for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + 1)) {
    const ranges = new Map();
    for (const { item, offset } of pos.slice(at, at + needle.length)) {
      const r = ranges.get(item);
      if (r) r.end = offset + 1;
      else ranges.set(item, { item, start: offset, end: offset + 1 });
    }
    found.push([...ranges.values()]);
  }
  return found;
}
