// Reads lines of [{doc, page, quote}] on stdin and prints a line for each with each cite's ok: the site highlights the
// quote at one place on the page, either as contiguous text or down one column. found: the site highlights it at one
// place or more.
import fs from "node:fs";
import readline from "node:readline";
import { matchRanges, squash } from "../web/static/highlight.js";

const [itemsDir] = process.argv.slice(2);
const docs = {};
const count = (text, needle) => { let n = 0; for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + 1)) n++; return n; };
for await (const line of readline.createInterface({ input: process.stdin })) {
  const cites = JSON.parse(line);
  for (const c of cites) {
    docs[c.doc] ??= JSON.parse(fs.readFileSync(`${itemsDir}/${c.doc}.json`, "utf8"));
    const { strs = [], lefts = [] } = docs[c.doc][c.page] || {};
    const n = count(squash(strs.join("")), squash(c.quote));
    c.ok = n === 1 || (n === 0 && matchRanges(strs, c.quote, lefts).length > 0);
    c.found = n > 1 || c.ok;
  }
  console.log(JSON.stringify(cites));
}
