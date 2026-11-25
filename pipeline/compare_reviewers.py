"""Asks other reviewer models the review tasks that a replay asked, and compares their verdicts with the pinned reviewer's.

Usage: python3 -I pipeline/compare_reviewers.py <year> <replay_work_dir> <work_dir> <accepts> [api]
The replay work dir is one that tables.py or run.py wrote. Each model gets every task the pinned reviewer rejected,
and <accepts> of those it accepted. Answers go to data/<year>/evaluations/reviewer/answers.
The table goes to <work_dir>/compare/report.md.
"""
import json, os, pathlib, sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import ask, blobs, evaluate, extract, review, run, years  # noqa: E402

MODELS = (("claude-opus-5-5", "medium"), ("claude-sonnet-5-5", "high"))
SAVED = "evaluations/reviewer/answers"


def pinned_verdicts(replay):
    """{prompt sha: ok} for each review task of the replay, as its reviewer gate judged it."""
    with open(f"{replay}/facts/review/{extract.OUTCOMES}") as f:
        return {o["prompt"]: o["ok"] is True for o in json.load(f)}


def chosen(pinned, accepts):
    """Every prompt that pinned rejects, and the first accepts prompts it accepts, in a stable order."""
    return [p for p in pinned if not pinned[p]] + sorted(p for p in pinned if pinned[p])[:accepts]


def agreement(pinned, got):
    """(agreed, answered) on the prompts that pinned accepts and on those it rejects, and how many got no verdict."""
    def share(want):
        answered = [p for p in got if pinned[p] is want and got[p] is not None]
        return sum(got[p] is want for p in answered), len(answered)
    return dict(accepts=share(True), rejects=share(False), unanswered=sum(v is None for v in got.values()))


def main(year, replay, work, accepts, mode=""):
    if mode not in ("", "api"):
        raise SystemExit(f"Unknown mode {mode}")
    data = years.data_dir(int(year))
    pinned = pinned_verdicts(replay)
    prompts = chosen(pinned, int(accepts))
    texts = [pathlib.Path(replay, blobs.PROMPTS, p).read_text() for p in prompts]
    answer = run.Answers(data, ask.api() if mode == "api" else None, saved=data / SAVED)
    rows = ["| Reviewer | Agrees on accepts | Agrees on rejects | No verdict | Dollars |", "|---|---|---|---|---|"]
    for model, effort in MODELS:
        out = f"{work}/compare/{model}-{effort}"
        got = review.ask_each(out, answer, model, effort, texts)
        a = agreement(pinned, {p: v.get("ok") for p, v in zip(prompts, got)})
        dollars = sum(evaluate.cost(json.loads((data / SAVED / f"{ask.key(model, t, effort)}.json").read_text()))
                      for t in texts)
        rows.append(f"| {model} {effort} | {a['accepts'][0]}/{a['accepts'][1]} | {a['rejects'][0]}/{a['rejects'][1]} "
                    f"| {a['unanswered']} | {dollars:.2f} |")
        with open(f"{out}/verdicts.json", "w") as f:
            json.dump([dict(prompt=p, pinned=pinned[p], ok=v.get("ok"), reason=v.get("reason", ""))
                       for p, v in zip(prompts, got)], f, indent=1)
        pathlib.Path(work, "compare", "report.md").write_text("\n".join(rows) + "\n")
        print(rows[-1], flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
