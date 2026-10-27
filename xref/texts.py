"""texts.py <pdf_dir> <work>: writes the text each check reads, per PDF.

work/text: pypdfium2 flow text, which quotes are counted against.
work/layout: pdftotext -layout, which models read.
work/items: pdf.js text items, which the site highlights.
"""
import os, subprocess, sys

import pypdfium2 as pdfium

HERE = os.path.dirname(os.path.abspath(__file__))


def main(pdf_dir, work):
    for d in ("text", "layout"):
        os.makedirs(f"{work}/{d}", exist_ok=True)
    for f in sorted(os.listdir(pdf_dir)):
        if not f.endswith(".pdf"):
            continue
        src, doc = os.path.join(pdf_dir, f), f[:-4]
        if not os.path.exists(f"{work}/text/{doc}.txt"):
            pdf = pdfium.PdfDocument(src)
            with open(f"{work}/text/{doc}.txt", "w") as w:
                for i in range(len(pdf)):
                    w.write(f"=====PAGE {i + 1}=====\n" + pdf[i].get_textpage().get_text_range() + "\n")
        if not os.path.exists(f"{work}/layout/{doc}.txt"):
            pages = subprocess.run(["pdftotext", "-layout", src, "-"], capture_output=True, text=True, check=True).stdout
            with open(f"{work}/layout/{doc}.txt", "w") as w:
                for i, page in enumerate(pages.split("\f")[:-1]):
                    w.write(f"=====PAGE {i + 1}=====\n{page}\n")
    subprocess.run(["node", f"{HERE}/items.mjs", pdf_dir, f"{work}/items"], check=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
