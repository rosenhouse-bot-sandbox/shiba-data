Reviewer claude-opus-5-5-high accepted 0/33 (0.0-0.104) decoys and cost $1.74.
The reviewer is the same model as one reader and some verifiers, so it may favor them.

| Reader | Precision | Recall | Expected lines shown | Unanswered | $ |
|---|---|---|---|---|---|
| claude-haiku-5-5-low | 135/147 (0.863-0.953) | 135/204 (0.594-0.723) | 16/19 (0.624-0.945) | 0 | 0.08 |
| claude-haiku-5-5-medium | 143/145 (0.951-0.996) | 143/204 (0.635-0.76) | 15/19 (0.567-0.915) | 0 | 0.10 |
| claude-haiku-5-5-high | 129/145 (0.828-0.931) | 129/204 (0.564-0.696) | 16/19 (0.624-0.945) | 0 | 0.16 |
| claude-sonnet-5-5-low | 92/101 (0.839-0.952) | 92/204 (0.384-0.52) | 15/19 (0.567-0.915) | 1 | 0.78 |
| claude-sonnet-5-5-medium | 112/129 (0.799-0.916) | 112/204 (0.48-0.616) | 16/19 (0.624-0.945) | 0 | 0.79 |
| claude-sonnet-5-5-high | 144/151 (0.907-0.977) | 144/204 (0.64-0.764) | 18/19 (0.754-0.991) | 0 | 1.17 |
| claude-opus-5-5-low | 110/118 (0.872-0.965) | 110/204 (0.471-0.606) | 18/19 (0.754-0.991) | 0 | 1.86 |
| claude-opus-5-5-medium | 135/178 (0.691-0.815) | 135/204 (0.594-0.723) | 19/19 (0.832-1.0) | 0 | 2.05 |
| claude-opus-5-5-high | 173/177 (0.943-0.991) | 173/204 (0.792-0.891) | 19/19 (0.832-1.0) | 0 | 2.29 |

| Verifier | Decoys accepted | Accepts the reviewer's accepts | Rejects the reviewer's rejects | Unanswered | $ |
|---|---|---|---|---|---|
| claude-sonnet-5-5-low | 0/33 (0.0-0.104) | 387/562 (0.649-0.726) | 78/102 (0.674-0.836) | 4 | 0.85 |
| claude-sonnet-5-5-medium | 0/33 (0.0-0.104) | 449/562 (0.764-0.83) | 77/102 (0.663-0.828) | 3 | 0.66 |
| claude-sonnet-5-5-high | 0/33 (0.0-0.104) | 549/562 (0.961-0.986) | 62/102 (0.511-0.697) | 0 | 0.83 |
| claude-opus-5-5-low | 0/33 (0.0-0.104) | 528/562 (0.917-0.956) | 81/102 (0.706-0.861) | 0 | 1.44 |
| claude-opus-5-5-medium | 0/33 (0.0-0.104) | 549/562 (0.961-0.986) | 79/102 (0.684-0.845) | 0 | 1.64 |

Intervals are 95% Wilson intervals.
Cheapest reader whose intervals reach claude-opus-5-5-high's precision and recall: claude-opus-5-5-high.
Cheapest verifier that accepts no decoy and at least 90% of the reviewer's accepts: claude-sonnet-5-5-high.
