"""A plan's EOC text, and whether a quote can be cited on a page."""
import csv, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "repro", "data")


def norm(s):
    return re.sub(r"\s+", " ", s.replace("￾", "")).strip()


def load_pages(path):
    parts = re.split(r"=====PAGE (\d+)=====\n", open(path).read())
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def eoc(plan_id, data=DATA):
    """The plan's EOC: (doc id, url)."""
    for d in csv.DictReader(open(f"{data}/documents_checked.csv")):
        if d["kind"] == "EOC" and plan_id in d["plan_ids"].split(";"):
            return d["sha256"][:16], d["url"]


class Doc:
    def __init__(self, work, plan_id, data=DATA):
        self.work, self.plan_id = work, plan_id
        self.id, self.url = eoc(plan_id, data)
        self._flow = None

    def pages(self, kind):
        return load_pages(f"{self.work}/{kind}/{self.id}.txt")

    @property
    def flow(self):
        if self._flow is None:
            self._flow = {p: norm(t) for p, t in self.pages("text").items()}
        return self._flow

    def highlights(self, cites):
        """Whether the site highlights each {page, quote} at exactly one place."""
        if not cites:
            return []
        r = subprocess.run(["node", f"{HERE}/match.mjs", f"{self.work}/items"], capture_output=True, text=True, check=True,
                           input=json.dumps([{"doc": self.id, "page": int(c["page"]), "quote": norm(c["quote"])} for c in cites]))
        return [c["ok"] for c in json.loads(r.stdout)]

    def quote_ok(self, page, quote):
        """At most once in the flow text, and highlighted at one place. Flow text misses quotes read down a column."""
        return self.flow.get(page, "").count(norm(quote)) <= 1 and self.highlights([{"page": page, "quote": quote}])[0]
