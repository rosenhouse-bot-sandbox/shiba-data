Reviewer claude-opus-5-5-high accepted 0/144 (0.0-0.026) decoys and cost $7.66.
The reviewer is the same model as one reader and some verifiers, so it may favor them.

| Reader | Precision | Recall | Expected lines shown | Unanswered | $ |
|---|---|---|---|---|---|
| claude-haiku-5-5-low | 638/703 (0.884-0.927) | 637/1123 (0.538-0.596) | 37/41 (0.775-0.961) | 0 | 0.36 |
| claude-haiku-5-5-medium | 691/738 (0.916-0.952) | 681/1123 (0.578-0.635) | 36/41 (0.745-0.947) | 0 | 0.44 |
| claude-haiku-5-5-high | 710/824 (0.836-0.884) | 702/1123 (0.596-0.653) | 37/41 (0.775-0.961) | 0 | 0.64 |
| claude-sonnet-5-5-low | 454/505 (0.87-0.922) | 454/1123 (0.376-0.433) | 33/41 (0.66-0.898) | 0 | 3.89 |
| claude-sonnet-5-5-medium | 664/720 (0.9-0.94) | 664/1123 (0.562-0.62) | 38/41 (0.806-0.975) | 0 | 4.27 |
| claude-sonnet-5-5-high | 801/818 (0.967-0.987) | 798/1123 (0.683-0.736) | 40/41 (0.874-0.996) | 0 | 5.18 |
| claude-opus-5-5-low | 606/662 (0.892-0.934) | 606/1123 (0.51-0.569) | 39/41 (0.839-0.987) | 0 | 7.95 |
| claude-opus-5-5-medium | 824/881 (0.917-0.95) | 824/1123 (0.707-0.759) | 40/41 (0.874-0.996) | 0 | 8.96 |
| claude-opus-5-5-high | 862/882 (0.965-0.985) | 862/1123 (0.742-0.791) | 40/41 (0.874-0.996) | 0 | 10.18 |

| Verifier | Decoys accepted | Accepts the reviewer's accepts | Rejects the reviewer's rejects | Unanswered | $ |
|---|---|---|---|---|---|
| claude-sonnet-5-5-low | 0/144 (0.0-0.026) | 2027/2564 (0.774-0.806) | 286/384 (0.699-0.786) | 14 | 3.23 |
| claude-sonnet-5-5-medium | 0/144 (0.0-0.026) | 2327/2564 (0.896-0.918) | 279/384 (0.68-0.769) | 5 | 3.23 |
| claude-sonnet-5-5-high | 0/144 (0.0-0.026) | 2529/2564 (0.981-0.99) | 233/384 (0.557-0.654) | 0 | 3.63 |
| claude-opus-5-5-low | 0/144 (0.0-0.026) | 2426/2564 (0.937-0.954) | 235/384 (0.562-0.659) | 0 | 6.43 |
| claude-opus-5-5-medium | 0/144 (0.0-0.026) | 2479/2564 (0.959-0.973) | 291/384 (0.713-0.798) | 0 | 7.11 |

Intervals are 95% Wilson intervals.
Cheapest reader whose intervals reach claude-opus-5-5-high's precision and recall: claude-opus-5-5-high.
Cheapest verifier that accepts no decoy and at least 90% of the reviewer's accepts and 75% of its rejects: claude-opus-5-5-medium.
