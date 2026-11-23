"""A document's page text, and whether a quote can be cited on a page."""
import json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PDFIUM_SOFT_HYPHEN = "￾"


def norm(s):
    return re.sub(r"\s+", " ", s.replace(PDFIUM_SOFT_HYPHEN, "")).strip()


def load_pages(path):
    with open(path) as f:
        parts = re.split(r"=====PAGE (\d+)=====\n", f.read())
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def highlights(work, cites, result="ok"):
    """Whether the site highlights each {doc, page, quote} at exactly one place, or with result="found", at any."""
    r = subprocess.run(["node", f"{HERE}/match.mjs", f"{work}/items"], capture_output=True, text=True, check=True,
                       input=json.dumps([{"doc": c["doc"], "page": int(c["page"]), "quote": norm(c["quote"])} for c in cites]))
    return [c[result] for c in json.loads(r.stdout)]


class Doc:
    def __init__(self, work, doc_id):
        self.work = work
        self.id = doc_id
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
        return highlights(self.work, [dict(c, doc=self.id) for c in cites])

    def quote_ok(self, page, quote):
        """At most once in the flow text, and highlighted at one place. Flow text misses quotes read down a column."""
        return self.flow.get(page, "").count(norm(quote)) <= 1 and self.highlights([{"page": page, "quote": quote}])[0]
