# Data Sources

## Letterboxd account export

User-provided ZIP only; the project does not scrape Letterboxd. Supported files are ratings, watched, diary, reviews, watchlist, and `likes/films.csv`. Archive SHA-256 fingerprints and per-user source keys make imports repeatable without duplicating records. Uncertain mappings remain staged and do not enter canonical training interactions. Account exports are private and gitignored.

## TMDB API

The canonical live catalog and metadata source. `TMDB_API_KEY` is required only for TMDB calls. The client retries transient network failures and surfaces rate limiting. Search responses are stored in a TTL cache; details/credits/keywords endpoints remain incomplete. Usage must follow TMDB attribution and API terms.

## MovieLens 32M

The exact MovieLens 32M release was downloaded through Kaggle's HTTPS mirror after the official GroupLens files host presented an expired TLS certificate. The downloader verifies `movies.csv`, `links.csv`, `ratings.csv`, and `tags.csv` against GroupLens' published checksums. Current ingestion consumes movies and links and streams ratings; tags are preserved but deferred. The artifact builder fingerprints its three consumed inputs and records exact ID mappings alongside its CSR matrix, so training runs remain traceable to dataset version `9ded58306c28`. Raw data and ML artifacts are gitignored, and use must follow the license/readme included in the archive.

Future sources include Tag Genome, replaceable sentence embeddings, and an optional LLM review analyzer. OpenAI is not required for Phase 1 and will not choose recommendations.
