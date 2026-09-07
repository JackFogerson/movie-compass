# Phase 1 Results

Status: real personal data imported, identity mapping substantially complete, MovieLens models trained, and initial repeated held-out evaluation complete.

## Personal import snapshot — 2026-08-31

- Profile: anonymized local evaluation profile
- Unique rated/watched films: 143
- Watchlist entries: 30
- Liked films: 53
- Review records: 147 across all 143 unique films
- Diary entries: 117
- Explicit rewatches: 4
- Mean rating: 3.479 / 5
- Rating range: 0.5–5.0
- Ratings of 4.0 or higher: 60
- Ratings of 2.0 or lower: 13
- Release-year range: 1957–2026
- Median release year in this history: 2023

The history is large enough to attempt held-out rating evaluation, although repeated splits will be needed because 143 ratings still produce relatively small test sets. Review-text modeling is available: the export contains 26,409 review characters across 147 review records. Four films have two reviews; only each film's most recent review is used as its active taste signal.

## Current coverage

- TMDB mappings: 142 / 143 (99.3%): 131 automatic and 11 audited metadata-assisted decisions. No ambiguities remain. `My Hero Academia: More` (2026) is retained as an unresolved catalog miss.
- MovieLens coverage: 70 / 142 canonical rated films (49.3%). The benchmark was collected in October 2023, while this profile is weighted heavily toward newer releases.
- Canonical personal interactions ready for modeling: 142.
- Models trained: popularity, genre/decade content, 64-factor collaborative, and weighted hybrid.
- MovieLens artifact: `movielens-32m-9ded58306c28` (32,000,204 ratings; 200,948 users; 87,585 movies).

## Initial held-out evaluation

Five deterministic 80/20 splits were run over the 70 MovieLens-linked personal ratings. Each split trained on 56 ratings and tested on 14.

| Model | Mean MAE | Mean RMSE |
| --- | ---: | ---: |
| Popularity | 0.600 | 0.752 |
| Content | 0.545 | 0.744 |
| Collaborative | 0.555 | 0.721 |
| Hybrid | **0.517** | **0.702** |

The hybrid is the strongest of the implemented models on aggregate, improving MAE by 13.9% over popularity and 5.2% over the next-best content baseline. This is encouraging proof-of-concept evidence, not a final quality claim: the linked sample is small, individual splits vary, and the current content features are limited to genres and release decade.

The remaining Phase 1 work is to tune weights without contaminating held-out tests, add top-K relevance evaluation where the data permits it, inspect and improve unseen-film recommendations, and document the largest errors and weaknesses.

## First live current-catalog run

The live ranker queried TMDB by primary release date from 2023-09-01 through 2027-02-27, considered 200 candidates, excluded already watched and watchlisted films, and produced 20 recommendations. New movies absent from MovieLens are explicitly labeled `cold_start`; they are not silently assigned collaborative evidence they do not have.

After rich TMDB enrichment and regularization tuning, the first five were:

1. Here the Whole Time (2026) — 3.841
2. One Night Only (2026) — 3.834
3. Swapped (2026) — 3.824
4. Lucky Strike (2026) — 3.776
5. Dune: Part Two (2024) — 3.771

Cold-start features now cover genre, director, top cast, keywords, original language, release era, synopsis TF-IDF, and a reliability-adjusted TMDB rating prior. Across five 80/20 splits of all 142 mapped personal ratings, tuned rich content achieved MAE 0.637 and RMSE 0.864 versus 0.645 and 0.923 for the train-mean baseline. The RMSE gain is meaningful, but the MAE gain is small; this list remains a proof of current-catalog personalization rather than a mature ranking claim. Semantic review-text signals, calibrated uncertainty, and ranking-level evaluation remain Phase 1/2 improvements.

## All-years candidate coverage

The default recommendation scope now merges both sources instead of restricting the engine to current releases. The first combined run used 250 high-support MovieLens/TMDB back-catalog candidates and 200 live recent TMDB candidates, yielding 410 unique unseen candidates after deduplication and exclusions. Its top 30 spans 1940–2019.

The first five all-years recommendations were:

1. The Shawshank Redemption (1994) — 4.175
2. Schindler's List (1993) — 4.161
3. Amélie (2001) — 4.143
4. Apocalypse Now (1979) — 4.141
5. Paths of Glory (1957) — 4.135

Each result includes its release year, candidate origin, score mode, and component scores. The CLI exposes `all`, `recent`, and `catalog` scopes plus minimum and maximum year bounds, matching the intended frontend filters. Separate views are important because MovieLens-backed catalog films have stronger collaborative evidence than TMDB-only new releases; combining raw scores without labels would hide that confidence difference.

## Review-text experiment

The latest local review for each of 142 mapped films was converted into a signed TF-IDF theme profile. Four review-affinity strengths were evaluated across the same five held-out splits. None improved MAE over the tuned rich-content model; the best RMSE change was negligible. Review affinity was therefore rejected as a ranking feature.

Review text remains useful for conservative explanations. It never leaves the local machine and never changes recommendation scores. Explanations appear only when total candidate affinity is positive and at least 0.003; examples include `CIA / war / army` for Apocalypse Now, `Shakespeare / historical` for Ran, and `universe / love / choice` for Dune: Part Two. Every report explicitly records `review_signal_affects_score: false`.

## Ranking metrics and API

The all-years top 30 has intra-list genre diversity 0.836, normalized genre entropy 0.912, 16 unique genres, 12 unique primary genres, and eight represented decades spanning 1940–2019. All 30 have MovieLens evidence; their mean self-information novelty is 3.762 bits with median rating support 14,664.

The recent top 20 has genre diversity 0.818, normalized entropy 0.917, 14 unique genres, and nine unique primary genres. All 20 are correctly labeled cold-start, so MovieLens novelty is reported as unavailable rather than fabricated.

The read-only FastAPI layer serves available scopes and precomputed recommendations with minimum year, maximum year, and result-limit filters. Responses retain explanations and source ranking metrics. These filters operate on stored ranked reports; dynamic on-request candidate generation and reranking remain future work.

## Local frontend

The responsive local frontend defaults to `all` scope with no year minimum or maximum, making the absence of a date restriction explicit. Users can switch between all-years and recent pools, apply year bounds, and change result count. Each card shows rank position, expected rating out of five, evidence level, the exact formula rationale, genres, score components, and conservative review-theme explanations where validated.

For MovieLens-backed items, the rationale states that expected rating uses 55% collaborative fit, 35% personal metadata fit, and 10% popularity prior. For TMDB-only items, it states that the estimate uses 80% metadata fit and 20% reliability-adjusted public rating and does not claim collaborative history.
