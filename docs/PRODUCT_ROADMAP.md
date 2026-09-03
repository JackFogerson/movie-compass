# Product Roadmap and Ideas

## Recommended next stages

1. **Profile-aware TMDB enrichment** — prioritize unsynced titles using genres, directors, keywords, eras, languages, popularity tier, and the active profile instead of global popularity alone.
2. **Feedback loop** — add watched, liked, disliked, not interested, and “why was this recommended?” controls; update the personal layer without retraining MovieLens.
3. **Group-ranking evaluation** — the two-to-four-person interface and balanced scorer are implemented; next compare average satisfaction, least-misery, veto-safe, and discovery-friendly objectives using simulated and real group feedback.
4. **Confidence and calibration dashboard** — distinguish expected rating, plausible interval, evidence strength, and cold-start uncertainty; monitor calibration as new ratings arrive.
5. **Catalog resolution interface** — expose ambiguous Letterboxd matches, missing TMDB records, and duplicate/title-edition decisions in the frontend.
6. **Production hardening** — background jobs, progress reporting, authentication, encrypted private exports, rate limiting, backups, and deployment.

## Feature ideas worth considering

- **Familiar-to-adventurous dial:** move between safe favorites and taste-expanding discoveries.
- **Tonight mode:** runtime, mood, intensity, language, release era, and available time.
- **Group disagreement map:** show who is enthusiastic, uncertain, or likely to veto each movie.
- **Fair group modes:** highest average, maximize the lowest score, minimize disagreement, or rotate whose taste gets priority.
- **Double-feature builder:** pair two complementary films by theme, era, director, or tonal contrast.
- **Taste eras:** compare how a person's preferences changed over time without allowing old reviews to override the latest review for the same film.
- **Director/actor/genre rabbit holes:** explain the connection and offer a curated sequence through a filmography.
- **Serendipity budget:** guarantee a chosen number of under-the-radar or unfamiliar recommendations in each list.
- **Streaming availability:** filter by country and services while keeping availability separate from recommendation quality.
- **Private share session:** let a group combine temporary local profiles without permanently exposing individual histories.
- **Post-watch calibration:** ask for the actual rating and show whether the prediction was accurate, surprising, or systematically biased.
- **Why not this movie?:** search a title and explain both positive matches and the factors holding its expected score down.
