# Personal Movie Recommender

A production-oriented, measurable hybrid recommendation engine centered on personal Letterboxd history. Phase 1 now includes real import, identity mapping, MovieLens training, held-out evaluation, live and all-years ranking, a read-only API, and a local responsive frontend.

## What works now

- FastAPI application with typed configuration, health, profile import, saved reports, and dynamic recommendation endpoints.
- PostgreSQL 16 + pgvector development service and an initial Alembic migration.
- Idempotent MovieLens 32M download/extract checks, SHA-256 reporting, catalog/link parsing, chunked rating reads, statistics, and compressed catalog output.
- Letterboxd export ZIP parsing for ratings, watched, diary, reviews, watchlist, and film likes. Missing files are accepted; interactions are merged using Letterboxd URI or normalized title/year.
- TMDB client with retries and a conservative title/year matcher that reports matched, ambiguous, or unresolved outcomes.
- An 87,000+ title local candidate universe covering every TMDB-linked MovieLens title plus cached current TMDB-only releases, with watched/watchlist exclusion, hybrid scoring, and a primary-genre diversity cap.
- Audience-reach filters for blockbuster, popular, cult classic, under-the-radar, and unknown/emerging titles. Reach is kept separate from predicted quality.
- Per-profile Letterboxd ZIP upload, local-first catalog matching, and on-demand model fitting. Only the latest review per film is used, while rewatch counts are retained. Imports return structured JSON even when TMDB is temporarily unreachable, and unmapped films remain safely pending.

Automatic scheduled TMDB enrichment, comparative group-ranking evaluation, authentication, and deployment are not yet complete.

## Fast setup on another Windows laptop

Clone the private repository, open PowerShell in it, and run:

```powershell
.\setup.ps1
.\start.ps1
```

The setup script securely asks for the TMDB key once, writes it only to the gitignored
local `.env`, installs the application, and initializes a private SQLite profile database.
The shared 87,000+ title MovieLens catalog and collaborative model are bundled, so there
is no dataset download or multi-hour training step. In the current installation, choose
**Manage profile → Download profile**; on the other laptop choose **Add profile** and use
that ZIP. Only rated films, latest reviews, watched dates, and rewatch counts are moved.

### Opening the project in Codex on another laptop

Add or clone `https://github.com/JackFogerson/movie-compass` as a Codex project, open a
task in that project, and ask Codex to run `setup.ps1` and start the app. The repository
contains no user profile. The one-time setup installs dependencies and asks you to enter
the TMDB key locally; after that, import the profile ZIPs and ranking can use the bundled
catalog/model immediately without downloading MovieLens or retraining the shared model.

TMDB cache files are intentionally refreshed locally instead of stored in Git history:
TMDB limits API-data caching to six months, while Git history is permanent. The API key
is also never committed. See `THIRD_PARTY_NOTICES.md`.

## Manual/development setup

Requires Python 3.11+, Docker, and enough disk space for MovieLens 32M.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload
```

When Docker/PostgreSQL is unavailable, a private SQLite database can be used for local experiments:

```powershell
# Set DATABASE_URL=sqlite+pysqlite:///./data/personal.sqlite3 in .env
python scripts/init_local_db.py
```

This is a development fallback only; PostgreSQL remains the production target. The SQLite file is gitignored.

Download MovieLens with `python scripts/download_movielens.py`. Import a Letterboxd export into PostgreSQL with:

```powershell
$env:PYTHONPATH="backend;."
python -m app.cli.import_letterboxd path\to\letterboxd-export.zip --report-path data\processed\letterboxd-import.json
```

The import is safe to repeat: archive hashes record completed runs, while source records are upserted by user and Letterboxd URI/title-year key. Add `--map-tmdb` to process the first mapping batch using `TMDB_API_KEY`, or `--mapping-limit 500` to change its size. TMDB searches are cached in PostgreSQL for the configured TTL.

Review uncertain matches without accepting them:

```powershell
python -m app.cli.review_mappings --user default --status ambiguous
python -m app.cli.review_mappings --user default --status unresolved
```

Approve a recorded candidate or reject the source record. Every decision is retained in an audit table:

```powershell
python -m app.cli.resolve_mapping 42 --tmdb-id 1091 --reason "Verified 1982 release"
python -m app.cli.resolve_mapping 43 --reject --reason "Not a feature film"
```

Use `--no-persist` on the import command for parse/report-only inspection.

Build a fingerprinted sparse MovieLens artifact after downloading the dataset:

```powershell
python -m app.cli.prepare_movielens
python -m app.cli.train_baselines ml\artifacts\movielens-32m-<version> --user default
python -m app.cli.train_collaborative ml\artifacts\movielens-32m-<version> --factors 64
python -m app.cli.evaluate ml\artifacts\movielens-32m-<version> --user default --seed 42
python -m app.cli.recommend ml\artifacts\movielens-32m-<version> --user default --limit 20
```

The first command makes a CSR ratings matrix, exact MovieLens user/movie ID maps, a linked catalog, and a source-hash manifest. The second always trains the Bayesian popularity baseline. It trains the personal content baseline only when at least two rated movies have a TMDB-to-MovieLens link; otherwise it records a clear skipped status instead of inventing a model.

Collaborative training learns item factors from bias-adjusted MovieLens ratings. Evaluation fits personal factors and the content model only on the training portion of a seeded personal split, then reports held-out MAE and RMSE for popularity, content, collaborative, and fixed-weight prototype hybrid models. Ten linked personal ratings are the minimum for the command to run; substantially more are needed for stable conclusions.

The recommendation command defaults to `--scope all`, merging a strong MovieLens/TMDB-linked back catalog from every year with TMDB's live recent catalog. Use `--scope recent` or `--scope catalog` for either pool alone, and `--year-min` / `--year-max` for explicit year filtering. Candidates with MovieLens links use the evaluated hybrid. TMDB-only candidates use a labeled cold-start score learned from all TMDB-mapped personal ratings and local features covering genre, director, cast, keywords, language, release era, and synopsis, plus a reliability-adjusted TMDB rating prior. Already watched films and, by default, watchlisted films are excluded. Use `--include-watchlist` to retain watchlist entries. Enriched TMDB responses are cached in the gitignored processed-data directory; ratings and reviews are never sent to TMDB.

The command also builds a local signed theme profile from the latest review for each mapped film. After every changed import, the app evaluates that person's review signal independently over five seeded held-out splits and several candidate weights. It requires at least 15 usable reviewed ratings, at least 0.01 MAE improvement, and no RMSE regression before review affinity may alter ranking. Otherwise it is used only for conservative explanations when a candidate strongly overlaps with positively weighted review themes. The selected per-profile policy and `review_signal_affects_score` are recorded in the report.

Saved reports and local dynamic reranking are available through the API:

```text
GET /recommendations/{user}/scopes
GET /recommendations/{user}?scope=all&year_min=1980&year_max=1999&limit=20
POST /recommendations/{user}/refresh?year_min=1980&year_max=1999&popularity=cult_classic
POST /profiles/import
GET /movies/search/{user}?q=Alien&limit=10
POST /groups/recommendations
POST /groups/search
```

The response includes explanations, score provenance, popularity tier, ranking metrics, a held-out-residual plausible-rating interval, and the five lowest expected scores in the selected year/popularity view. The point estimate remains optimized for held-out error; the interval communicates the wider range of ratings the user might actually give. The title-search endpoint scores matching movies for the selected profile across the full local catalog. Refreshes rerank the local candidate universe and do not require a live TMDB request. A future background catalog job will consume TMDB's daily valid-ID export and selectively enrich promising IDs; the ID export alone does not contain enough metadata to score every film responsibly.

Start the API and frontend together:

```powershell
uvicorn app.main:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000/`. The frontend separates personal recommendations and Movie Night into dedicated tabs, automatically lists every saved ranking-ready profile, and defaults to all years. It exposes genre, year, audience-reach, and result-count controls. Every card shows its rank, expected rating, evidence level, personalized rationale, genres, positive matches, and profile-specific cautions. The bottom-five sections explicitly explain the weak fit instead of presenting only reasons someone might enjoy the title.

The group endpoints evaluate a shared candidate set for two to four imported profiles, expose every person's expected score and plausible range, and balance 60% average satisfaction with 40% protection for the lowest prediction plus a small disagreement penalty. Movie Night includes specific-title lookup, five shared least-likely matches, and five widest individual-rating disagreements. Watched movies are excluded by default; an optional rewatch mode applies a linear 0.20-point maximum penalty according to the fraction of the group that has seen each title. Personal and group rankings support genre, year, popularity, and result-count filters. Broad shared shortlists use a one-pass group scorer, large read-only model artifacts are reused in memory, and identical profile/filter shortlists are cached until the next import. Alternative group objectives still require comparative evaluation.

Sync TMDB's complete valid movie-ID universe and enrich it in controlled batches:

```powershell
python -m app.cli.sync_tmdb_catalog
python -m app.cli.enrich_tmdb_catalog --limit 100
```

The sync streams TMDB's gzip JSON-lines export into a compact SQLite popularity index, records its SHA-256 and source date, and excludes video records from movie eligibility. Enrichment skips titles already covered by MovieLens or the rich-details cache, then fetches a bounded high-priority batch. `GET /catalog/status` reports the synced universe without exposing private profile data.

See `PROJECT_STATUS.md` for a direct assessment of what is currently usable.

Run `pytest` and `ruff check .` for verification. Never commit `.env`, account exports,
profile databases, TMDB cache files, or personal model artifacts. The explicitly allowlisted
shared MovieLens artifact is the sole model-data exception.
