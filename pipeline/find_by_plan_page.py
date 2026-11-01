"""Finds Aetna, Devoted and UHC documents on each plan's page, and rewrites those carriers' rows in found.csv.

Usage: python3 -I find_by_plan_page.py <year>

Aetna and UHC pages need JavaScript, so headless Chromium renders every page.
"""
import csv
import html.parser
import json
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_docs  # noqa: E402
import years  # noqa: E402

UHC_COUNTIES = {"Multnomah": ("97201", "051"), "Clackamas": ("97045", "005")}
LABELS = {"Summary of Benefits": "SB", "Evidence of Coverage": "EOC"}
RENDER = """
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const pages = [];
  for (const url of JSON.parse(process.argv[1])) {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForFunction(() => [...document.querySelectorAll("a[href]")].some(
      a => /^(View \\d{4} )?Evidence of Coverage/.test(a.textContent.trim())), null, { timeout: 60000 }).catch(() => {});
    pages.push(await page.content());
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(pages));
})();
"""


def page_url(p, year, county):
    contract, plan, segment = p["plan_id"].split("-")
    if p["organization"] == "Aetna Medicare":
        return f"https://www.aetna.com/medicare/plan.{contract}.{plan}.html"
    if p["organization"] == "Devoted Health":
        return f"https://www.devoted.com/plan-documents/benefit-and-coverage-details/{contract}-{plan}-{int(segment):03}-{year}/"
    if p["organization"] == "UnitedHealthcare":
        zip_code, fips = UHC_COUNTIES[county]
        return (f"https://www.aarpmedicareplans.com/health-plans/details.html/{zip_code}/{fips}/"
                f"{contract}{plan}{int(segment):03}/{year}")
    return None


class Anchors(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors, self.open = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.open = dict(attrs, text="")
            self.anchors.append(self.open)

    def handle_endtag(self, tag):
        if tag == "a":
            self.open = None

    def handle_data(self, data):
        if self.open is not None:
            self.open["text"] += data


def links(page, url):
    """Returns (kind, url, label) for English SB, EOC and UHC optional-services links."""
    parser = Anchors()
    parser.feed(page)
    found = []
    for a in parser.anchors:
        text = " ".join(a["text"].split())
        name = re.sub(r"^View \d{4} | \([^)]*\)", "", text)
        if "Español" in text or not a.get("href"):
            continue
        if name in LABELS:
            row = (LABELS[name], urllib.parse.urljoin(url, a["href"]), "")
        elif "Optional Services" in a.get("dtmname", ""):
            row = ("RIDER", urllib.parse.urljoin(url, a["href"]), name)
        else:
            continue
        if row not in found:
            found.append(row)
    return found


def render(urls):
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
    out = subprocess.run(["node", "-e", RENDER, json.dumps(urls)], capture_output=True, text=True, check=True,
                         env=dict(os.environ, NODE_PATH=root))
    return json.loads(out.stdout)


def main(year, render=render):
    data = years.data_dir(year)
    county = years.config(data)["counties"][0]
    plans = [p for p in find_docs.read(data / "generated/plans.csv") if page_url(p, year, county)]
    urls = [page_url(p, year, county) for p in plans]
    rows = []
    for p, url, page in zip(plans, urls, render(urls)):
        found = links(page, url)
        for kind in find_docs.KINDS:
            if kind not in {k for k, _, _ in found}:
                print(f"::warning::No {kind} on {url}")
        rows += [dict(plan_ids=p["plan_id"], kind=kind, url=doc,
                      found_via=f"carrier plan page {url}" + (f', "{label}"' if label else ""))
                 for kind, doc, label in found]
    ours = {p["plan_id"] for p in plans}
    rows += [r for r in find_docs.read(data / "found.csv") if not set(r["plan_ids"].split(";")) <= ours]
    with open(data / "found.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=find_docs.COLUMNS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(int(sys.argv[1]))
