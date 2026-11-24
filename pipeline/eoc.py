"""A document's page text, and whether a quote can be cited on a page."""
import atexit, functools, json, os, re, subprocess, threading

HERE = os.path.dirname(os.path.abspath(__file__))
PDFIUM_SOFT_HYPHEN = "￾"


def norm(s):
    return re.sub(r"\s+", " ", s.replace(PDFIUM_SOFT_HYPHEN, "")).strip()


def load_pages(path):
    with open(path) as f:
        parts = re.split(r"=====PAGE (\d+)=====\n", f.read())
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


class Matcher:
    """A node process that runs match.mjs on one line of cites at a time."""
    def __init__(self, items):
        self.node = subprocess.Popen(["node", f"{HERE}/match.mjs", items], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True)
        atexit.register(self.close)

    def __call__(self, cites):
        self.node.stdin.write(json.dumps(cites) + "\n")
        self.node.stdin.flush()
        return json.loads(self.node.stdout.readline())

    def close(self):
        self.node.stdin.close()
        self.node.wait()
        self.node.stdout.close()


_matchers = threading.local()
# Each (items dir, doc, page, quote) checked, with its ok and found. A run checks the same quote many times.
_checked = {}


def highlights(work, cites, result="ok"):
    """Whether the site highlights each {doc, page, quote} at exactly one place, or with result="found", at any."""
    items = f"{work}/items"
    keys = [(items, c["doc"], int(c["page"]), norm(c["quote"])) for c in cites]
    new = list(dict.fromkeys(k for k in keys if k not in _checked))
    if new:
        matchers = _matchers.__dict__.setdefault("by_items", {})
        if items not in matchers:
            matchers[items] = Matcher(items)
        got = matchers[items]([dict(doc=doc, page=page, quote=quote) for _, doc, page, quote in new])
        _checked.update(zip(new, got))
    return [_checked[k][result] for k in keys]


@functools.cache
def flow(path):
    """Each page's text in reading order, normalized. A run checks quotes in the same document many times."""
    return {p: norm(t) for p, t in load_pages(path).items()}


class Doc:
    def __init__(self, work, doc_id):
        self.work = work
        self.id = doc_id

    def pages(self, kind):
        return load_pages(f"{self.work}/{kind}/{self.id}.txt")

    @property
    def flow(self):
        return flow(f"{self.work}/text/{self.id}.txt")

    def highlights(self, cites):
        """Whether the site highlights each {page, quote} at exactly one place."""
        return highlights(self.work, [dict(c, doc=self.id) for c in cites])

    def quote_ok(self, page, quote):
        """At most once in the flow text, and highlighted at one place. Flow text misses quotes read down a column."""
        return self.flow.get(page, "").count(norm(quote)) <= 1 and self.highlights([{"page": page, "quote": quote}])[0]
