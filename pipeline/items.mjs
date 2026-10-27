// Writes each PDF's pdf.js text items and their left edges per page, as the site's viewer sees them.
import fs from "node:fs";
import path from "node:path";
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";

const [pdfDir, outDir] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
for (const file of fs.readdirSync(pdfDir).filter((f) => f.endsWith(".pdf"))) {
  const out = path.join(outDir, file.replace(/\.pdf$/, ".json"));
  if (fs.existsSync(out)) continue;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(fs.readFileSync(path.join(pdfDir, file))), verbosity: 0 }).promise;
  const pages = {};
  for (let n = 1; n <= doc.numPages; n++) {
    const items = (await (await doc.getPage(n)).getTextContent()).items.filter((i) => "str" in i);
    pages[n] = { strs: items.map((i) => i.str), lefts: items.map((i) => Math.round(i.transform[4])) };
  }
  fs.writeFileSync(out, JSON.stringify(pages));
}
