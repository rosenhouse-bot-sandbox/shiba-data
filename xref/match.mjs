// Reads [{doc, page, quote}] on stdin and prints each one's ok: the site highlights the quote at one place on the page,
// either as contiguous text or down one column.
import fs from "node:fs";
import { matchRanges } from "../web/static/highlight.js";

const [itemsDir] = process.argv.slice(2);
const docs = {};
const squash = (s) => s.replace(/\s+/g, "").toLowerCase();
const count = (text, needle) => text.split(needle).length - 1;
const cites = JSON.parse(fs.readFileSync(0, "utf8"));
for (const c of cites) {
  docs[c.doc] ??= JSON.parse(fs.readFileSync(`${itemsDir}/${c.doc}.json`, "utf8"));
  const { strs = [], lefts = [] } = docs[c.doc][c.page] || {};
  const n = count(squash(strs.join("")), squash(c.quote));
  c.ok = n === 1 || (n === 0 && matchRanges(strs, c.quote, lefts).length > 0);
}
console.log(JSON.stringify(cites));
