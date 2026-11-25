"""Asks the pinned reviewer about cited, trusted facts that have no saved answer to their review task.

Usage: python3 -I pipeline/rereview.py <year> <texts_dir> <work_dir> <limit> [api]
It asks about at most <limit> facts and writes the verdicts to <work_dir>/rereview/outcomes.json.
"""
import os, sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import ask, extract, facts, review, run, years  # noqa: E402


def unanswered(data, rows, answered, present_version):
    """The facts in rows, once each, that a cell cites, that reviewed_facts.csv trusts, and that are not answered."""
    cited = review.cited(data, rows, present_version) & review.trusted(data, rows, present_version)
    return [f for r, f in {review.row(f): f for f in rows}.items() if r in cited and not answered(f)]


def first(rows, limit):
    """The first limit rows in a stable order, so each rerun asks about the next ones."""
    return sorted(rows, key=lambda f: ask.sha(repr(review.row(f))))[:limit]


def main(year, texts, work, limit, mode=""):
    if mode not in ("", "api"):
        raise SystemExit(f"Unknown mode {mode}")
    data = years.data_dir(int(year))
    pins = run.steps.versions(data, run.STEPS)
    version = run.STEPS["document_facts"][pins["document_facts"]]
    model, effort = version["reviewer"]
    task_of = review.reviewer_task(data, texts, version)
    pending = unanswered(data, facts.read(data / "machine/document_facts.csv"),
                         lambda f: review.saved(data, model, task_of(f), effort), pins["present"])
    chosen = first(pending, int(limit))
    print(f"{len(pending)} trusted facts have no saved review. Asking about {len(chosen)}.")
    texts_of = [task_of(f) for f in chosen]
    answer = run.Answers(data, ask.api() if mode == "api" else None)
    got = review.ask_each(f"{work}/rereview/tasks", answer, model, effort, texts_of)
    extract.write_outcomes(f"{work}/rereview", [review.outcome(f, t, v, earlier=True)
                                                 for f, t, v in zip(chosen, texts_of, got)])
    print(f"The reviewer rejected {sum(v.get('ok') is not True for v in got)} of {len(got)}.")


if __name__ == "__main__":
    main(*sys.argv[1:])
