# Roadmap

## Phase 0 — Foundation (in progress)

- [x] Layout, dependencies, settings, logging, FastAPI skeleton, Docker, migration, docs, tests
- [ ] PostgreSQL integration test
- [ ] Remaining genre, people, credit, keyword, recommendation, feedback, and model-version tables

## Phase 1 — Measurable proof of concept (started)

- [x] MovieLens downloader, validation, hashing, parsers, links, and chunked ratings
- [x] Letterboxd ZIP parser and import report foundation
- [x] Conservative TMDB client/matcher boundary
- [x] Persist idempotent imports and mapping review records
- [x] Durable TMDB cache and resumable batch mapper
- [x] Audited manual approval/rejection workflow for ambiguous mapping candidates
- [x] Fingerprinted sparse MovieLens training artifacts
- [x] Popularity and basic personal content baselines
- [x] Initial latent-factor collaborative model and personal factor projection
- [x] Prototype hybrid rating predictor
- [x] Seeded held-out MAE/RMSE evaluator and train/evaluate CLIs
- [ ] Ranking metrics, repeated/time-aware splits, weight tuning, and recommendation CLI
- [ ] Measured `docs/PHASE_1_RESULTS.md`

Phases 2–7 add rich metadata and embeddings, review intelligence, ranking improvements, the API, frontend, and feedback. Each signal must improve held-out performance to earn its complexity.
