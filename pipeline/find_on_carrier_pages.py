"""Finds Wellcare, ATRIO and AgeRight SBs and EOCs on each carrier's plan-materials page.

Usage: python3 -I find_on_carrier_pages.py <year>

Rewrites these carriers' rows in data/<year>/found.csv and keeps the other rows.
It stops without writing if a plan lacks an SB or EOC, or has two of one kind.
"""
import csv
import html.parser
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import years  # noqa: E402
from find_docs import COLUMNS, KINDS, read  # noqa: E402

# Each page's URL, and text that each of the year's document links contains.
PAGES = {"Wellcare": ("https://www.wellcareor.com/plan-benefit-materials.html", "/aep/{year}/"),
         "ATRIO Health Plans": ("https://atriohp.com/oregon/members/{year}-benefit-plans/", ""),
         "AgeRight Advantage": ("https://agerightadvantage.com/for-members/plan-documents/", "")}
KIND_BY_TEXT = {"Summary of Benefits": "SB", "Summary of Benefits - English (PDF)": "SB",
                "Evidence of Coverage": "EOC", "Evidence of Coverage - English (PDF)": "EOC"}
PLAN_IN_FILENAME = re.compile(r"(?<![a-z0-9])(H\d{4})_(\d{3})(?:_(\d)(?![a-z0-9]))?", re.I)
RENDER = """
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(process.argv[1], { waitUntil: "networkidle", timeout: 90000 });
  process.stdout.write(await page.content());
  await browser.close();
})();
"""


class Links(html.parser.HTMLParser):
    """Collects (href, text, index of the enclosing <ul>) for each link."""

    def __init__(self):
        super().__init__()
        self.links, self.uls, self.ul_count, self.href, self.text = [], [], 0, None, ""

    def handle_starttag(self, tag, attrs):
        if tag == "ul":
            self.ul_count += 1
            self.uls.append(self.ul_count)
        elif tag == "a":
            self.href, self.text = dict(attrs).get("href"), ""

    def handle_endtag(self, tag):
        if tag == "ul" and self.uls:
            self.uls.pop()
        elif tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.text.split()), self.uls[-1] if self.uls else None))
            self.href = None

    def handle_data(self, data):
        self.text += data


def named_plans(href, plans):
    """Returns the plans in `plans` that the link's filename names, or None if it names no plan."""
    filename = urllib.parse.urlparse(href).path.rsplit("/", 1)[-1]
    named = PLAN_IN_FILENAME.findall(filename)
    if not named:
        return None
    ids = set()
    for contract, number, segment in named:
        prefix = f"{contract.upper()}-{number}-"
        ids |= {p for p in plans if p == prefix + segment or (not segment and p.startswith(prefix))}
    return ids


def found_via(page_url):
    u = urllib.parse.urlparse(page_url)
    return f"carrier page ({u.netloc.removeprefix('www.')}{u.path})"


def documents(page_html, page_url, plans, year_mark=""):
    """Returns found.csv rows for the SB and EOC links that contain `year_mark` and name a plan in `plans`.

    A link whose filename names no plan, like ATRIO's shared SB, belongs to the plans its list names."""
    parser = Links()
    parser.feed(page_html)
    plans_in_list = {}
    for href, _, ul in parser.links:
        plans_in_list.setdefault(ul, set()).update(named_plans(href, plans) or ())
    by_url = {}
    for href, text, ul in parser.links:
        kind = KIND_BY_TEXT.get(text)
        ids = named_plans(href, plans)
        if ids is None:
            ids = plans_in_list[ul] if ul else set()
        if kind and ids and year_mark in href:
            by_url.setdefault((kind, urllib.parse.urljoin(page_url, href)), set()).update(ids)
    for kind in KINDS:
        for p in plans:
            urls = [u for (k, u), ids in by_url.items() if k == kind and p in ids]
            if len(urls) != 1:
                raise SystemExit(f"{page_url} links {len(urls)} {kind}s for {p}: {urls}")
    rows = [dict(plan_ids=";".join(p for p in plans if p in ids), kind=kind, url=url, found_via=found_via(page_url))
            for (kind, url), ids in by_url.items()]
    return sorted(rows, key=lambda r: (plans.index(r["plan_ids"].split(";")[0]), r["kind"] != "SB"))


def render(url):
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
    return subprocess.run(["node", "-e", RENDER, url], stdout=subprocess.PIPE, text=True, check=True,
                          env=dict(os.environ, NODE_PATH=root)).stdout


def main(year, fetch=render):
    data = years.data_dir(int(year))
    plans = read(data / "generated/plans.csv")
    found = []
    for org, (page, year_mark) in PAGES.items():
        url = page.format(year=year)
        ids = [p["plan_id"] for p in plans if p["organization"] == org]
        found += documents(fetch(url), url, ids, year_mark.format(year=year))
    ours = {p["plan_id"] for p in plans if p["organization"] in PAGES}
    kept = [r for r in read(data / "found.csv") if not set(r["plan_ids"].split(";")) & ours]
    with open(data / "found.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(kept + found)


if __name__ == "__main__":
    main(*sys.argv[1:])
