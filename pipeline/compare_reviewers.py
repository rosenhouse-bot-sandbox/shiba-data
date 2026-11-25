"""Asks other reviewer models the review tasks that a replay asked, and compares their verdicts with the pinned reviewer's.

Usage: python3 -I pipeline/compare_reviewers.py <year> <replay_work_dir> <work_dir> <accepts> [api]
The replay work dir is one that tables.py or run.py wrote. Each model gets every task the pinned reviewer rejected,
and <accepts> of those it accepted. Answers go to data/<year>/evaluations/reviewer/answers.
"""
import csv, json, os, pathlib, sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import ask, blobs, evaluate, review, run, years  # noqa: E402

MODELS = (("claude-opus-5-5", "medium"), ("claude-sonnet-5-5", "high"))
SAVED = "evaluations/reviewer/answers"


def chosen(pinned, accepts):
    """Every prompt that pinned rejects, and the first accepts prompts it accepts, in a stable order."""
    return [p for p in pinned if not pinned[p]] + sorted(p for p in pinned if pinned[p])[:accepts]


def agreement(pinned, got):
    """(agreed, asked) on the prompts that pinned accepts and on those it rejects. A missing verdict rejects."""
    def share(want):
        asked = [p for p in got if pinned[p] is want]
        return sum((got[p] is True) is want for p in asked), len(asked)
    return dict(accepts=share(True), rejects=share(False))


def pinned_verdicts(data, work, model, effort):
    """{prompt sha: ok} for each review task in the replay's ledger, from the pinned reviewer's saved answers."""
    out = {}
    with open(f"{work}/{blobs.LEDGER}") as f:
        for t in csv.DictReader(f):
            if t["dir"].startswith("facts/review") and (t["model"], t["effort"]) == (model, effort):
                with open(data / "answers" / f"{t['key']}.json") as a:
                    out[t["prompt"]] = (ask.array(json.load(a)["reply"]) or [{}])[0].get("ok") is True
    return out


def main(year, replay, work, accepts, mode=""):
    if mode not in ("", "api"):
        raise SystemExit(f"Unknown mode {mode}")
    data = years.data_dir(int(year))
    version = run.STEPS["document_facts"][run.steps.versions(data, run.STEPS)["document_facts"]]
    pinned = pinned_verdicts(data, replay, *version["reviewer"])
    prompts = chosen(pinned, int(accepts))
    texts = [pathlib.Path(replay, blobs.PROMPTS, p).read_text() for p in prompts]
    answer = run.Answers(data, ask.api() if mode == "api" else None, saved=data / SAVED)
    print("| Reviewer | Agrees on accepts | Agrees on rejects | Dollars |\n|---|---|---|---|")
    for model, effort in MODELS:
        got = review.ask_each(f"{work}/compare/{model}-{effort}", answer, model, effort, texts)
        a = agreement(pinned, {p: v.get("ok") for p, v in zip(prompts, got)})
        dollars = sum(evaluate.cost(json.loads((data / SAVED / f"{ask.key(model, t, effort)}.json").read_text()))
                      for t in texts)
        print(f"| {model} {effort} | {a['accepts'][0]}/{a['accepts'][1]} | {a['rejects'][0]}/{a['rejects'][1]} | {dollars:.2f} |")


if __name__ == "__main__":
    main(*sys.argv[1:])
