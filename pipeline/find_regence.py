"""Finds Regence SBs on its plan shopping site, and EOCs by guessing from each SB URL.

Usage: python3 -I find_regence.py <plans.csv> <found.csv> <links.csv> <year>

Rewrites the Regence rows of found.csv. Needs Playwright in the global node_modules and poppler's pdftotext.
"""
import csv
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

# The ZIP and county pick Multnomah. The list opens on Medicare Supplement plans, so each tab needs a click.
RENDER = r'''
const { chromium } = require('playwright');
const list = `https://regence1.destinationrx.com/PC/${process.argv[1]}/Shopping/PlanList?ZipCode=97201&CountyFips=41051`;
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const open = async tab => {
    await page.goto(list, {waitUntil: 'networkidle', timeout: 90000});
    await page.getByText(tab).first().click();
    await page.waitForTimeout(4000);
  };
  const pages = [];
  for (const tab of ['Medicare Advantage Prescription Drug Plans', 'Medicare Advantage Plans']) {
    await open(tab);
    const buttons = await page.$$eval('button', es => es.map(e => e.getAttribute('aria-label') || '')
                                                      .filter(s => s.endsWith(': View plan details')));
    for (const name of buttons) {
      await open(tab);
      await page.getByRole('button', {name}).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(3000);
      pages.push([page.url(), await page.content()]);
    }
  }
  console.log(JSON.stringify(pages));
  await browser.close();
})();
'''


def render(year):
    env = dict(os.environ, NODE_PATH=subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip())
    return json.loads(subprocess.run(["node", "-e", RENDER, str(year)], capture_output=True, text=True, check=True,
                                     env=env).stdout)


def fetch(url):
    """Returns the URL after redirects and the text of the PDF's first page, which is empty when the URL fails."""
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            final, pdf = r.url, r.read()
    except urllib.error.URLError:
        return url, ""
    return final, subprocess.run(["pdftotext", "-l", "1", "-", "-"], input=pdf, capture_output=True).stdout.decode()


def details(html):
    contract, plan, segment = re.search(r"Plan: (H\d{4})-(\d{3})-(\d{3})", html).groups()
    sb = re.search(r'href="([^"]*/summary-[^"]*\.pdf)"', html).group(1)
    return f"{contract}-{plan}-{int(segment)}", sb


def found_rows(pages, plans, fetch, known):
    """Prints a warning for each guessed EOC that does not name its plan or say Evidence of Coverage.

    A known URL that ends at the found one's folder is kept, because citations name documents by URL.
    """
    def fetch_known(url):
        url, text = fetch(url)
        folder = url[:url.rindex("/") + 1]
        return folder if folder in known else url, text

    names = {p["plan_id"]: p["plan_name"] for p in plans}
    rows, listed = [], set()
    for page_url, html in pages:
        plan_id, sb = details(html)
        if plan_id not in names:
            print(f"::warning::The site lists {plan_id}, which plans.csv lacks")
            continue
        listed.add(plan_id)
        source = f"carrier plan page ({page_url})"
        rows.append(dict(plan_ids=plan_id, kind="SB", url=fetch_known(sb)[0], found_via=source))
        eoc = sb.replace("/summary-", "/eoc-")
        url, text = fetch_known(eoc)
        cover = " ".join(text.split())
        if "Evidence of Coverage" in cover and names[plan_id] in cover:
            rows.append(dict(plan_ids=plan_id, kind="EOC", url=url,
                             found_via=f"SB link from {source} with summary- changed to eoc-, checked against the cover"))
        else:
            print(f"::warning::{eoc} is not the EOC of {plan_id}")
    for plan_id in sorted(names.keys() - listed):
        print(f"::warning::The site does not list {plan_id}")
    return rows


def merge(found, new, plan_ids):
    return [r for r in found if not set(r["plan_ids"].split(";")) & plan_ids] + new


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(plans_csv, found_csv, links_csv, year):
    plans = [p for p in read(plans_csv) if p["organization"].startswith("Regence")]
    found = read(found_csv)
    columns = list(found[0])
    known = {r["url"] for r in read(links_csv)}
    rows = merge(found, found_rows(render(year), plans, fetch, known), {p["plan_id"] for p in plans})
    with open(found_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(*sys.argv[1:])
