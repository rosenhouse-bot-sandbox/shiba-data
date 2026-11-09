"""Terms the pipeline view explains, each with the code behind it at the build's commit."""
import ast

REPO_URL = "https://github.com/rosenhouse-bot-sandbox/shiba-data"

# ref is "<path>:<function or constant>" for Python, or a path to link whole. {year} names the year's data.
TERMS = {
    "bothCounties": {"title": "Plans sold in both counties", "ref": "pipeline/universe.py:select_plans",
                     "text": "Code keeps a plan only if the Landscape file lists it in every county in config.json, "
                             "and drops special needs plans for people with Medicaid or in institutions."},
    "firstUrl": {"title": "First URL wins", "ref": "pipeline/find_docs.py:documents",
                 "text": "Browser finds come first, then the Links sheet, then URL patterns. "
                         "A plan keeps the first URL found for each kind of document."},
    "cover": {"title": "Cover check", "ref": "pipeline/fetch_docs.py:cover_check",
              "text": "The first pages must show the year, every plan ID, the right kind of document and both counties. "
                      "Any problem is recorded in cover_problems."},
    "layoutText": {"title": "Text that keeps the page's columns", "ref": "pipeline/texts.py:main",
                   "text": "pdftotext -layout keeps a benefit table's two columns side by side, "
                           "so a model can tell which cost belongs to which row."},
    "pbpFields": {"title": "PBP ambulance fields", "ref": "pipeline/main_chart.py:ambulance",
                  "text": "Line 1 spans the ground and air ambulance copays and coinsurance. "
                          "Line 2 is the worldwide emergency transportation cost, or \"not covered\"."},
    "prompt": {"title": "The prompt", "ref": "pipeline/fact_prompt.md",
               "text": "One prompt per document and benefit group: the task, the words each field may use, "
                       "and only the pages that mention the group."},
    "hash": {"title": "Saved answers", "ref": "pipeline/ask.py:key",
             "text": "Each answer is filed under a hash of the model, effort and prompt. "
                     "A rerun with the same prompt reads the file instead of calling Claude."},
    "quoteCheck": {"title": "Quote check", "ref": "pipeline/extract.py:problem",
                   "text": "Each quote must occur exactly once on its page, so the site can highlight it, "
                           "and the quotes must show every number in the amount."},
    "decoy": {"title": "Decoys", "ref": "pipeline/extract.py:decoys",
              "text": "A real fact's amount and quotes moved to another plan, network or setting. "
                      "If the verifier accepts one, the run fails."},
    "reviewer": {"title": "Reviewer", "ref": "pipeline/review.py:gate",
                 "text": "Claude Opus checks each fact a value would cite, one fact per prompt. "
                         "A run stops before spending if too many facts need a new answer."},
    "rule": {"title": "The Ambulance rule", "ref": "pipeline/present.py:ambulance",
             "text": "Written in code from the domain expert's instructions: "
                     "line 1 is trips in the U.S., line 2 is trips abroad."},
    "bestSource": {"title": "Best source", "ref": "pipeline/present.py:top",
                   "text": "Among matching facts, a rule keeps those from the best source: EOC, then rider, then SB, then CMS."},
    "added": {"title": "Added facts", "ref": "data/{year}/added_facts.csv",
              "text": "Facts a Claude session wrote where the extracted facts fell short, each with a note. "
                      "The site marks the cell with a green note."},
    "blankClaim": {"title": "Blank-cell claims", "ref": "pipeline/blanks.py:gate_claims",
                   "text": "Claude Haiku says why a cell is blank: excluded, Medicare-only or optional. "
                           "Code keeps a claim only if every quote passes the quote check."},
    "layer": {"title": "Layers", "ref": "pipeline/layers.py:LAYERS",
              "text": "Tables applied in order on top of the draft. A later layer that sets a value wins. "
                      "Some layers only attach citations."},
    "worker": {"title": "The Worker", "ref": "web/worker.js",
               "text": "A Cloudflare Worker serves the static site, and serves each PDF from R2 by its hash."},
}


def locate(repo, ref):
    """The source and line span of a Python function or top-level constant."""
    path, name = ref.split(":")
    source = (repo / path).read_text()
    for node in ast.parse(source).body:
        names = [node.name] if isinstance(node, ast.FunctionDef) else \
            [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        if name in names:
            return ast.get_source_segment(source, node), node.lineno, node.end_lineno
    raise ValueError(f"{path} has no {name}")


def resolve(repo, commit, year):
    out = {}
    for term, t in TERMS.items():
        ref = t["ref"].format(year=year)
        base = f"{REPO_URL}/blob/{commit}/{ref.split(':')[0]}"
        if ":" in ref:
            code, start, end = locate(repo, ref)
            url, where = f"{base}#L{start}-L{end}", ref.replace(":", ": ")
        else:
            # A year's data may not be in this checkout, as in tests.
            if "{year}" not in t["ref"] and not (repo / ref).exists():
                raise ValueError(f"{ref} does not exist")
            code, url, where = "", base, ref
        out[term] = {"title": t["title"], "text": t["text"], "code": code, "url": url, "where": where}
    return out
