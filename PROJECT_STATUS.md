# Project Status

## Current stage

The project is in the later-middle portion of Phase 1: Recommendation Engine Proof of Concept. The GitHub base app contains no profiles or personal database. Local-first identity matching lets a fresh installation use bundled MovieLens/TMDB metadata before remote lookup, while live TMDB enrichment supplies current titles, posters, and streaming availability. The 2026-08-31 TMDB daily export is indexed locally: 1,176,123 eligible movie IDs after video exclusion, with 87,000+ MovieLens-linked titles immediately rankable.

The ingestion and experimental ML pipeline is usable by a developer. MovieLens 32M models have been trained and five real personal held-out splits show the hybrid beating all three component baselines on average. Live and all-years rankers produce unseen-film recommendations, including movies absent from MovieLens. The API and responsive local frontend now serve dynamic single-profile and two-to-four-person group rankings, year and audience-reach filters, expected ratings, explanations, and metrics. It is a usable local proof of concept, not yet a deployed product.

## Usable now

- Parse and persist Letterboxd exports without scraping.
- Map films local-first, then use TMDB with caching, ambiguity preservation, and audited manual review when network access and authorization are available.
- Download/parse MovieLens and create fingerprinted sparse artifacts.
- Train popularity, basic content, and latent-factor collaborative models.
- Fit a personal collaborative vector without retraining MovieLens.
- Run a seeded held-out comparison reporting MAE/RMSE and individual prediction errors.
- Merge all-years MovieLens/TMDB back-catalog candidates with a rolling live TMDB release window.
- Filter recommendations by pool scope and minimum/maximum release year.
- Label MovieLens-backed hybrid scores separately from TMDB-only cold-start scores.
- Exclude watched/watchlisted films and cap repetition by primary genre.
- Reevaluate review-theme scoring separately after each changed profile import; enable it only when five seeded held-out splits clear the accuracy gate, otherwise retain review themes for explanations only.
- Measure coverage, genre diversity/entropy, decade breadth, novelty support, source balance, and score spread.
- Serve precomputed scopes and year-filtered results through validated FastAPI endpoints.
- Browse a responsive local frontend defaulting to all years, with expected-rating provenance on every card.
- Search the local catalog for a profile-specific expected score and inspect the five lowest expected matches in the active filter.
- Rank a shared candidate set for two to four profiles, with individual expected scores/ranges, genre filtering, title lookup, bottom-five and taste-divergence lists, plus optional proportionally penalized rewatches.
- Inspect a profile's complete rated-film history in a newest-first popup without exposing it outside the local profile database.
- Sync the complete TMDB valid-ID universe and selectively enrich high-priority uncached titles in bounded batches.

## Not yet product-usable

- The initial hybrid weights have been evaluated but not systematically tuned.
- Ranking metrics exist, but there is no offline top-K relevance/recall evaluation because the personal history is small and heavily recent.
- Only 70 of 142 canonical personal ratings link to MovieLens 32M; recent releases after its October 2023 collection window require TMDB-first cold-start handling.
- Rich TMDB cold-start metadata is available, but its five-split validation gain is modest.
- There is no calibrated probabilistic confidence, feedback workflow, authentication, or deployment.

## Gate to complete Phase 1

With the real Letterboxd history now imported, resolve enough mappings, train against the full MovieLens artifact, run repeated and preferably time-aware held-out evaluations, compare every model honestly, tune or reject the hybrid based on validation, and produce unseen-film recommendations plus `docs/PHASE_1_RESULTS.md`. Phase 1 succeeds only if the hybrid demonstrates useful improvement beyond simple baselines.

Mapping, MovieLens artifact construction, training, repeated evaluation, live/all-years ranking, profile-specific review-policy evaluation, ranking metrics, dynamic API ranking, group ranking, and the local frontend are complete. The initial anonymized evaluation achieved mean hybrid MAE 0.517 and RMSE 0.702 across five deterministic splits. Review text is evaluated separately for every changed profile over several candidate weights. It is enabled only with at least 15 usable reviewed ratings, at least 0.01 MAE improvement, and no RMSE regression. The next stage is an explicit feedback loop, stronger small-profile uncertainty handling, and comparative evaluation of group-ranking objectives.
