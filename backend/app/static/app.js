let user = document.body.dataset.user;
const tmdbStatus = document.querySelector("#tmdb-status");
const yearMinInput = document.querySelector("#year-min");
const yearMaxInput = document.querySelector("#year-max");
const limitInput = document.querySelector("#limit");
const popularityInput = document.querySelector("#popularity");
const certificationInput = document.querySelector("#certification");
const genreInput = document.querySelector("#genre");
const mediaTypeInput = document.querySelector("#media-type");
const runtimeInput = document.querySelector("#runtime");
const availabilityInput = document.querySelector("#availability");
const applyButton = document.querySelector("#apply");
const list = document.querySelector("#recommendations");
const metrics = document.querySelector("#metrics");
const notice = document.querySelector("#notice");
const template = document.querySelector("#movie-card-template");
const profileNameInput = document.querySelector("#profile-name");
const profileSelect = document.querySelector("#profile-select");
const profileSummary = document.querySelector("#profile-summary");
const profileDisplayNameInput = document.querySelector("#profile-display-name");
const profileIdInput = document.querySelector("#profile-id");
const saveProfileButton = document.querySelector("#save-profile");
const rebuildProfileButton = document.querySelector("#rebuild-profile");
const showProfileStatsButton = document.querySelector("#show-profile-stats");
const statsYearInput = document.querySelector("#stats-year");
const showProfileRatingsButton = document.querySelector("#show-profile-ratings");
const profileStats = document.querySelector("#profile-stats");
const ratingHistoryDialog = document.querySelector("#rating-history-dialog");
const ratingHistoryTitle = document.querySelector("#rating-history-title");
const ratingHistorySummary = document.querySelector("#rating-history-summary");
const ratingHistoryList = document.querySelector("#rating-history-list");
const closeRatingHistoryButton = document.querySelector("#close-rating-history");
const statMoviesDialog = document.querySelector("#stat-movies-dialog");
const statMoviesTitle = document.querySelector("#stat-movies-title");
const statMoviesSummary = document.querySelector("#stat-movies-summary");
const statMoviesList = document.querySelector("#stat-movies-list");
const closeStatMoviesButton = document.querySelector("#close-stat-movies");
const statCategoryDialog = document.querySelector("#stat-category-dialog");
const statCategoryTitle = document.querySelector("#stat-category-title");
const statCategorySummary = document.querySelector("#stat-category-summary");
const statCategoryTop = document.querySelector("#stat-category-top");
const statCategoryBottom = document.querySelector("#stat-category-bottom");
const closeStatCategoryButton = document.querySelector("#close-stat-category");
const showProfileAccuracyButton = document.querySelector("#show-profile-accuracy");
const exportProfileButton = document.querySelector("#export-profile");
const profileAccuracy = document.querySelector("#profile-accuracy");
const showAdultPostersInput = document.querySelector("#show-adult-posters");
const manualMovieQueryInput = document.querySelector("#manual-movie-query");
const manualMovieYearInput = document.querySelector("#manual-movie-year");
const findManualMovieButton = document.querySelector("#find-manual-movie");
const manualMovieResults = document.querySelector("#manual-movie-results");
const manualRatingFields = document.querySelector("#manual-rating-fields");
const selectedManualMovieLabel = document.querySelector("#selected-manual-movie");
const manualMovieRatingInput = document.querySelector("#manual-movie-rating");
const manualMovieReviewInput = document.querySelector("#manual-movie-review");
const saveManualRatingButton = document.querySelector("#save-manual-rating");
const manualRatingStatus = document.querySelector("#manual-rating-status");
const updateProfileArchiveInput = document.querySelector("#update-profile-archive");
const updateProfileButton = document.querySelector("#update-profile");
const updateProfileStatus = document.querySelector("#update-profile-status");
const deleteProfileConfirmation = document.querySelector("#delete-profile-confirmation");
const deleteProfileButton = document.querySelector("#delete-profile");
const profileEditorStatus = document.querySelector("#profile-editor-status");
const profileEditor = document.querySelector(".profile-editor");
const manageProfileSelect = document.querySelector("#manage-profile-select");
const profileManagementHost = document.querySelector("#profile-management-host");
const profilesEmptyState = document.querySelector("#profiles-empty-state");
const emptyProfileState = document.querySelector("#empty-profile-state");
const descriptorStatsCache = new Map();
let descriptorTooltip;
const profileArchiveInput = document.querySelector("#profile-archive");
const importButton = document.querySelector("#import-profile");
const importStatus = document.querySelector("#import-status");
const movieQueryInput = document.querySelector("#movie-query");
const movieSearchYearInput = document.querySelector("#movie-search-year");
const searchMovieButton = document.querySelector("#search-movie");
const searchStatus = document.querySelector("#search-status");
const searchResults = document.querySelector("#search-results");
const lowestList = document.querySelector("#lowest-recommendations");
const groupProfileInputs = [...document.querySelectorAll(".group-profile")];
const buildGroupButton = document.querySelector("#build-group");
const groupStatus = document.querySelector("#group-status");
const groupResults = document.querySelector("#group-results");
const groupYearMinInput = document.querySelector("#group-year-min");
const groupYearMaxInput = document.querySelector("#group-year-max");
const groupLimitInput = document.querySelector("#group-limit");
const groupPopularityInput = document.querySelector("#group-popularity");
const groupCertificationInput = document.querySelector("#group-certification");
const groupGenreInput = document.querySelector("#group-genre");
const groupMediaTypeInput = document.querySelector("#group-media-type");
const groupRuntimeInput = document.querySelector("#group-runtime");
const groupAvailabilityInput = document.querySelector("#group-availability");
const groupIncludeWatchedInput = document.querySelector("#group-include-watched");
const groupMovieQueryInput = document.querySelector("#group-movie-query");
const groupMovieSearchYearInput = document.querySelector("#group-movie-search-year");
const searchGroupMovieButton = document.querySelector("#search-group-movie");
const groupSearchStatus = document.querySelector("#group-search-status");
const groupSearchResults = document.querySelector("#group-search-results");
const groupLowestHeading = document.querySelector("#group-lowest-heading");
const groupLowestResults = document.querySelector("#group-lowest-results");
const groupDivisiveHeading = document.querySelector("#group-divisive-heading");
const groupDivisiveResults = document.querySelector("#group-divisive-results");
const viewTabs = [...document.querySelectorAll(".view-tab")];
profileManagementHost.append(profileEditor);
profileEditor.open = true;
let catalogStatus = null;
let savedProfiles = [];
let selectedManualMovie = null;
const adultPosterPreferenceKey = "movie-compass-show-adult-posters";

function applyAdultPosterPreference(show) {
  showAdultPostersInput.checked = show;
  document.body.classList.toggle("show-adult-posters", show);
  localStorage.setItem(adultPosterPreferenceKey, show ? "true" : "false");
}

function manualPosterMarkup(movie) {
  if (!movie.poster_url) return '<span class="manual-movie-poster-placeholder"></span>';
  const image = `<img src="${escapeHtml(movie.poster_url)}" alt="" loading="lazy" />`;
  if (!movie.adult) return image;
  return `<span class="manual-sensitive-poster" role="button" tabindex="0" aria-label="Adult poster hidden. Click to reveal.">${image}<em>Click to reveal</em></span>`;
}

function enableSensitivePosterReveal(option) {
  const poster = option.querySelector(".manual-sensitive-poster");
  if (!poster) return;
  const reveal = (event) => {
    event.preventDefault();
    event.stopPropagation();
    poster.classList.add("revealed");
    poster.removeAttribute("role");
    poster.removeAttribute("tabindex");
    poster.setAttribute("aria-label", "Adult poster revealed");
  };
  poster.addEventListener("click", reveal);
  poster.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") reveal(event);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadTmdbStatus() {
  try {
    const response = await fetch("/tmdb/status");
    const result = await responseJson(response);
    tmdbStatus.classList.remove("checking");
    tmdbStatus.classList.add(result.live ? "live" : "offline");
    tmdbStatus.textContent = result.live ? "TMDB live" : "TMDB offline · catalog active";
    tmdbStatus.title = result.message;
  } catch (_error) {
    tmdbStatus.classList.remove("checking");
    tmdbStatus.classList.add("offline");
    tmdbStatus.textContent = "TMDB status unavailable";
  }
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function scoreEvidence(movie) {
  if (Array.isArray(movie.individual_scores)) {
    return [
      ["Group average", movie.group_average],
      ["Lowest individual", movie.group_minimum],
      ["Taste spread", movie.group_spread],
      ["Rewatch penalty", movie.rewatch_penalty],
    ].map(([label, value]) => `<span><b>${label}:</b> ${Number(value || 0).toFixed(2)}</span>`).join("");
  }
  const values = [
    ["Metadata fit", movie.content_score],
    ["Collaborative", movie.collaborative_score],
    ["MovieLens audience prior", movie.popularity_score],
    ["TMDB public-rating prior", movie.public_rating_prior],
    ["Audience ratings", movie.audience_evidence_count?.toLocaleString()],
    ["TMDB votes", movie.tmdb_vote_count?.toLocaleString()],
  ];
  return values
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([label, value], index) => {
      const isScore = index < 4 && typeof value === "number";
      return `<span><b>${label}:</b> ${isScore ? `${value.toFixed(2)} / 5` : value}</span>`;
    })
    .join("");
}

function runtimeBounds(input) {
  if (!input.value) return [null, null];
  const [minimum, maximum] = input.value.split("-").map(Number);
  return [minimum, maximum];
}

function matchesAvailability(movie, selection) {
  if (selection === "all") return true;
  const types = new Set((movie.streaming || []).map((item) => item.type));
  if (selection === "listed") return types.size > 0;
  if (selection === "subscription") return types.has("subscription");
  if (selection === "free") return types.has("free") || types.has("free with ads");
  if (selection === "rent_buy") return types.has("rent") || types.has("buy");
  return true;
}

function certificationBucket(certification) {
  const normalized = String(certification || "").trim().toUpperCase();
  if (["G", "PG", "PG-13", "R", "NC-17"].includes(normalized)) return normalized.toLowerCase();
  if (["NR", "UNRATED", "NOT RATED"].includes(normalized)) return "unrated";
  return normalized ? "other" : "unknown";
}

function recommendationFiltered(movies, availability, certification, limit = null) {
  const filtered = (movies || []).filter((movie) =>
    matchesAvailability(movie, availability.value) &&
    (certification.value === "all" || certificationBucket(movie.certification) === certification.value)
  );
  return limit == null ? filtered : filtered.slice(0, limit);
}

function renderStreaming(movie) {
  const container = document.createElement("div");
  const options = movie.streaming || [];
  const country = movie.streaming_country || "US";
  if (options.length) {
    const grouped = new Map();
    options.forEach((item) => {
      if (!grouped.has(item.type)) grouped.set(item.type, []);
      grouped.get(item.type).push(item.service);
    });
    const rows = [...grouped.entries()].map(([type, services]) => {
      const visible = services.slice(0, 4).join(", ");
      const remaining = services.length > 4 ? ` +${services.length - 4}` : "";
      return `<li><b>${escapeHtml(type)}:</b> ${escapeHtml(visible)}${remaining}</li>`;
    });
    container.innerHTML = `<span>Watch in ${escapeHtml(country)}</span><ul>${rows.join("")}</ul>`;
  } else {
    container.innerHTML = `<span>No streaming listing found in ${escapeHtml(country)}</span>`;
  }
  if (movie.streaming_link) {
    const link = document.createElement("a");
    link.href = movie.streaming_link;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "Availability by JustWatch";
    container.append(link);
  }
  return container.innerHTML;
}

function descriptorPhrases(match) {
  const [rawKind, ...valueParts] = String(match).split(":");
  const kind = rawKind.trim().toLowerCase();
  const value = valueParts.join(":").trim();
  const titleCase = value.replace(/\b\w/g, (letter) => letter.toUpperCase());
  if (kind === "genre") return [`${value} films`];
  if (kind === "story/theme") return [
    `stories involving ${value}`,
    `stories centered on ${value}`,
    `period stories set in the ${value}`,
  ];
  if (kind === "director") return [
    `films directed by ${titleCase}`,
    `${titleCase}'s films`,
  ];
  if (kind === "cast member") return [`films featuring ${titleCase}`];
  if (kind === "release era") return [`films from the ${value}`, `movies from the ${value}`];
  if (kind === "original language") {
    const languageNames = { de: "German", es: "Spanish", fr: "French", it: "Italian", ja: "Japanese", ko: "Korean", zh: "Chinese" };
    return [
      `${value.toUpperCase()}-language films`,
      `${languageNames[value.toLowerCase()] || value.toUpperCase()}-language films`,
    ];
  }
  return [value || match];
}

function descriptorStat(profile, match) {
  const key = `${profile}|${match}`;
  if (!descriptorStatsCache.has(key)) {
    descriptorStatsCache.set(key, fetch(
      `/profiles/${encodeURIComponent(profile)}/stats/descriptor?match=${encodeURIComponent(match)}`,
    ).then(async (response) => {
      const result = await responseJson(response);
      if (!response.ok) throw new Error(result.detail || "Taste detail could not be loaded");
      return result;
    }));
  }
  return descriptorStatsCache.get(key);
}

function descriptorEntries(items) {
  const merged = new Map();
  items.forEach(({ match, users }) => {
    if (!match) return;
    const current = merged.get(match) || new Set();
    users.filter(Boolean).forEach((profile) => current.add(profile));
    merged.set(match, current);
  });
  return [...merged].map(([match, profiles]) => ({ match, users: [...profiles] }));
}

function linkifyDescriptorText(text, entries) {
  const source = String(text || "");
  const candidates = [];
  descriptorEntries(entries).forEach((entry) => {
    descriptorPhrases(entry.match).forEach((phrase) => {
      if (phrase) candidates.push({ ...entry, phrase });
    });
  });
  candidates.sort((left, right) => right.phrase.length - left.phrase.length);
  const spans = [];
  candidates.forEach((candidate) => {
    const needle = candidate.phrase.toLowerCase();
    let start = source.toLowerCase().indexOf(needle);
    while (start !== -1) {
      const end = start + needle.length;
      if (!spans.some((span) => start < span.end && end > span.start)) {
        spans.push({ start, end, match: candidate.match, users: candidate.users });
      }
      start = source.toLowerCase().indexOf(needle, end);
    }
  });
  spans.sort((left, right) => left.start - right.start);
  if (!spans.length) return escapeHtml(source);
  let cursor = 0;
  const html = [];
  spans.forEach((span) => {
    html.push(escapeHtml(source.slice(cursor, span.start)));
    html.push(`<button type="button" class="descriptor-link" data-match="${escapeHtml(span.match)}" data-users="${escapeHtml(span.users.join(","))}">${escapeHtml(source.slice(span.start, span.end))}</button>`);
    cursor = span.end;
  });
  html.push(escapeHtml(source.slice(cursor)));
  return html.join("");
}

function hideDescriptorTooltip(button) {
  button.dataset.tooltipVisible = "false";
  if (descriptorTooltip) descriptorTooltip.hidden = true;
}

async function showDescriptorTooltip(button) {
  button.dataset.tooltipVisible = "true";
  if (!descriptorTooltip) {
    descriptorTooltip = document.createElement("div");
    descriptorTooltip.className = "descriptor-tooltip";
    descriptorTooltip.hidden = true;
    document.body.append(descriptorTooltip);
  }
  descriptorTooltip.innerHTML = "<strong>Loading your taste history…</strong>";
  descriptorTooltip.hidden = false;
  const place = () => {
    const rect = button.getBoundingClientRect();
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - descriptorTooltip.offsetWidth - 12));
    const above = rect.top - descriptorTooltip.offsetHeight - 8;
    descriptorTooltip.style.left = `${left}px`;
    descriptorTooltip.style.top = `${above > 8 ? above : rect.bottom + 8}px`;
  };
  place();
  try {
    const profiles = button.dataset.users.split(",").filter(Boolean);
    const results = await Promise.all(profiles.map((profile) => descriptorStat(profile, button.dataset.match)));
    if (button.dataset.tooltipVisible !== "true") return;
    const heading = results.find((result) => result.value)?.value || button.textContent;
    const rows = results.map((result) => {
      const examples = result.movies.slice(0, profiles.length > 1 ? 2 : 5).map((movie) => `${movie.title} (${movie.rating.toFixed(1)} ★)`).join(" · ");
      return result.count
        ? `<span><b>${escapeHtml(result.display_name)}:</b> average ${result.observed_average.toFixed(2)} ★ across ${result.count} rated film${result.count === 1 ? "" : "s"}</span><span class="descriptor-films">${escapeHtml(examples)}${result.count > (profiles.length > 1 ? 2 : 5) ? " · …" : ""}</span>`
        : `<span><b>${escapeHtml(result.display_name)}:</b> no rated films with this exact descriptor</span>`;
    }).join("");
    descriptorTooltip.innerHTML = `<strong>${escapeHtml(heading)}</strong>${rows}<span>Click to see all matching movies.</span>`;
    place();
  } catch (error) {
    if (button.dataset.tooltipVisible === "true") {
      descriptorTooltip.innerHTML = `<strong>${escapeHtml(error.message)}</strong>`;
      place();
    }
  }
}

async function showDescriptorMovies(button) {
  try {
    const profiles = button.dataset.users.split(",").filter(Boolean);
    const results = await Promise.all(profiles.map((profile) => descriptorStat(profile, button.dataset.match)));
    const first = results[0];
    closeStatMoviesButton.textContent = "Close";
    statMoviesTitle.textContent = first?.value || button.textContent;
    statMoviesSummary.textContent = profiles.length > 1
      ? "Each group member's own ratings for this descriptor."
      : first.count
        ? `${first.count} rated movie${first.count === 1 ? "" : "s"} · actual average ${first.observed_average.toFixed(2)} ★.`
        : "No rated movies match this descriptor yet.";
    statMoviesList.innerHTML = results.map((result) => `
      ${profiles.length > 1 ? `<h3 class="descriptor-profile-heading">${escapeHtml(result.display_name)} · ${result.count ? `${result.observed_average.toFixed(2)} ★ average from ${result.count}` : "no matching ratings"}</h3>` : ""}
      ${result.movies.length ? result.movies.map((item) => `
          <article class="rating-history-row">
            ${item.poster_url ? `<img src="${escapeHtml(item.poster_url)}" alt="" loading="lazy" />` : '<span class="rating-history-poster-placeholder"></span>'}
            <div class="rating-history-copy"><div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.year ?? "Year unavailable")}${item.watched_date ? ` · watched ${escapeHtml(item.watched_date)}` : ""}</span></div>${item.review_text ? `<p>${escapeHtml(item.review_text)}</p>` : ""}</div>
            <div class="rating-history-score"><strong>${item.rating.toFixed(1)}</strong><span>★ / 5</span></div>
          </article>`).join("") : '<div class="empty compact-empty">No rated movies match this descriptor.</div>'}
    `).join("");
    statMoviesDialog.showModal();
  } catch (error) {
    searchStatus.textContent = error.message;
  }
}

function bindDescriptorLinks(card) {
  card.querySelectorAll(".descriptor-link").forEach((button) => {
    button.addEventListener("mouseenter", () => showDescriptorTooltip(button));
    button.addEventListener("mouseleave", () => hideDescriptorTooltip(button));
    button.addEventListener("focus", () => showDescriptorTooltip(button));
    button.addEventListener("blur", () => hideDescriptorTooltip(button));
    button.addEventListener("click", () => showDescriptorMovies(button));
  });
}

function renderMovie(movie, rankLabel = null) {
  const card = template.content.firstElementChild.cloneNode(true);
  card.querySelector(".rank").textContent = rankLabel || `#${movie.rank}`;
  card.querySelector(".movie-year").textContent = movie.year ?? "Year unavailable";
  card.querySelector(".movie-title").textContent = movie.title;
  const posterShell = card.querySelector(".poster-shell");
  const poster = card.querySelector(".movie-poster");
  if (movie.poster_url) {
    poster.src = movie.poster_url;
    poster.alt = `${movie.title} poster`;
  } else {
    posterShell.remove();
    card.classList.add("no-poster");
  }
  const expectedRating = Number(movie.expected_rating);
  card.querySelector(".expected-rating").textContent = Number.isFinite(expectedRating) ? expectedRating.toFixed(2) : "—";
  const uncertainty = movie.rating_uncertainty;
  const isGroup = Array.isArray(movie.individual_scores);
  card.querySelector(".rating-label").textContent = isGroup ? "GROUP FIT" : "EXPECTED";
  const groupMinimum = Number(movie.group_minimum);
  const groupMaximum = isGroup ? Math.max(...movie.individual_scores.map((item) => Number(item.expected_rating)).filter(Number.isFinite)) : null;
  card.querySelector(".plausible-range").textContent = isGroup && Number.isFinite(groupMinimum) && Number.isFinite(groupMaximum)
    ? `Individual range: ${groupMinimum.toFixed(1)}–${groupMaximum.toFixed(1)}`
    : uncertainty?.plausible_minimum != null
      ? `${Math.round(uncertainty.coverage * 100)}% plausible: ${uncertainty.plausible_minimum.toFixed(1)}–${uncertainty.plausible_maximum.toFixed(1)}`
      : "Uncertainty not calibrated";
  const expectation = movie.ranking_expectation;
  const badges = [
    `<span class="badge media-type">${movie.media_type === "tv" || Number(movie.tmdb_id) < 0 ? "Miniseries / TV" : "Movie"}</span>`,
    `<span class="badge popularity">${escapeHtml((movie.popularity_tier || "unclassified").replaceAll("_", " "))}</span>`,
    ...movie.genres.map((genre) => `<span class="badge">${escapeHtml(genre)}</span>`),
  ];
  if (movie.runtime) {
    badges.push(`<span class="badge runtime">${escapeHtml(movie.runtime_label || `${movie.runtime} min`)}</span>`);
  }
  badges.push(`<span class="badge certification">${escapeHtml(movie.certification || "Rating unknown")}</span>`);
  (movie.moods || []).forEach((mood) => badges.push(`<span class="badge mood">${escapeHtml(mood)}</span>`));
  const watchedCount = Number(movie.watched_count ?? movie.watched_by?.length ?? 0);
  if (isGroup && watchedCount > 0) {
    badges.push(`<span class="badge rewatch">Seen by ${watchedCount}/${movie.individual_scores.length}</span>`);
  }
  card.querySelector(".badges").innerHTML = badges.join("");
  card.querySelector(".streaming-info").innerHTML = renderStreaming(movie);
  const positiveEntries = isGroup
    ? movie.individual_scores.flatMap((item) => (item.positive_matches || []).map((match) => ({ match, users: [item.user] })))
    : (movie.metadata_matches || []).map((match) => ({ match, users: [user] }));
  const cautionEntries = isGroup
    ? movie.individual_scores.flatMap((item) => (item.caution_matches || []).map((match) => ({ match, users: [item.user] })))
    : (movie.caution_matches || []).map((match) => ({ match, users: [user] }));
  card.querySelector(".expectation-reason").innerHTML = linkifyDescriptorText(
    isGroup ? movie.group_reason : expectation.reason,
    positiveEntries,
  );
  const groupScores = card.querySelector(".group-scores");
  if (isGroup) {
    groupScores.innerHTML = movie.individual_scores.map((item) => `
      <div class="group-score-person">
        <b>${escapeHtml(item.display_name || item.user)}</b> · <strong>${Number.isFinite(Number(item.expected_rating)) ? Number(item.expected_rating).toFixed(2) : "—"}</strong>
        <span>${Number.isFinite(Number(item.plausible_minimum)) && Number.isFinite(Number(item.plausible_maximum)) ? `${Number(item.plausible_minimum).toFixed(1)}–${Number(item.plausible_maximum).toFixed(1)} plausible` : "Range unavailable"}</span>
        <span>${linkifyDescriptorText(item.reason, (item.positive_matches || []).map((match) => ({ match, users: [item.user] })))}</span>
      </div>`).join("");
  } else {
    groupScores.remove();
  }
  const explanationList = card.querySelector(".explanations");
  const primaryExplanation = String(isGroup ? movie.group_reason : expectation.reason)
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  const extraExplanations = (movie.why_you_may_like_it || movie.explanation?.slice(1) || [])
    .filter((value) => !primaryExplanation.includes(String(value).replace(/\s+/g, " ").trim().toLowerCase()));
  if (extraExplanations.length) {
    explanationList.innerHTML = extraExplanations
      .map((value) => `<li>${linkifyDescriptorText(value, positiveEntries)}</li>`)
      .join("");
  } else {
    explanationList.remove();
  }
  const riskBlock = card.querySelector(".risk-explanation");
  const cautions = movie.why_you_may_not_like_it || [];
  if (cautions.length) {
    riskBlock.querySelector("strong").textContent = isGroup
      ? "What might not work for the group"
      : "What might not click for you";
    riskBlock.querySelector(".cautions").innerHTML = cautions
      .map((value) => `<li>${linkifyDescriptorText(value, cautionEntries)}</li>`)
      .join("");
  } else {
    riskBlock.remove();
  }
  const metadata = card.querySelector(".movie-metadata");
  const metadataRows = [];
  if (movie.directors?.length) {
    metadataRows.push(`<p><b>Director:</b> ${escapeHtml(movie.directors.join(", "))}</p>`);
  }
  if (movie.cast?.length) {
    metadataRows.push(`<p><b>Cast:</b> ${escapeHtml(movie.cast.join(", "))}</p>`);
  }
  if (movie.synopsis) {
    metadataRows.push(`<p><b>Synopsis:</b> ${escapeHtml(movie.synopsis)}</p>`);
  }
  if (metadataRows.length) {
    metadata.querySelector(".metadata-copy").innerHTML = metadataRows.join("");
  } else {
    metadata.remove();
  }
  card.querySelector(".score-grid").innerHTML = scoreEvidence(movie);
  bindDescriptorLinks(card);
  return card;
}

function renderMetrics(report) {
  const source = report.source_ranking_metrics || report.ranking_metrics;
  if (!source) {
    metrics.innerHTML = "";
    return;
  }
  const diversity = source.diversity;
  const coverage = source.coverage;
  const diversityScore = Number(diversity?.intra_list_genre_diversity);
  metrics.innerHTML = [
    metric("Source candidates", coverage.candidates_considered),
    metric("Genre diversity", Number.isFinite(diversityScore) ? diversityScore.toFixed(2) : "—"),
    metric("Unique genres", diversity?.unique_genres ?? 0),
    metric("Decades represented", diversity?.distinct_decades ?? 0),
  ].join("");
}

function requestParams() {
  const params = new URLSearchParams({
    limit: availabilityInput.value === "all" && certificationInput.value === "all" ? limitInput.value : "100",
    popularity: popularityInput.value,
    media_type: mediaTypeInput.value,
  });
  if (yearMinInput.value) params.set("year_min", yearMinInput.value);
  if (yearMaxInput.value) params.set("year_max", yearMaxInput.value);
  if (genreInput.value) params.set("genre", genreInput.value);
  const [runtimeMinimum, runtimeMaximum] = runtimeBounds(runtimeInput);
  if (runtimeMinimum) params.set("runtime_min", runtimeMinimum);
  if (runtimeMaximum) params.set("runtime_max", runtimeMaximum);
  params.set("country", "US");
  return params;
}

function updateViewLabel(report) {
  const minLabel = yearMinInput.value;
  const maxLabel = yearMaxInput.value;
  let label = "All years · historical and current releases";
  if (minLabel && maxLabel) label = `${minLabel} through ${maxLabel}`;
  else if (minLabel) label = `${minLabel} and later`;
  else if (maxLabel) label = `Through ${maxLabel}`;
  const popularityLabel = popularityInput.options[popularityInput.selectedIndex].text;
  const genreLabel = genreInput.value || "All genres";
  const mediaTypeLabel = mediaTypeInput.options[mediaTypeInput.selectedIndex].text;
  const runtimeLabel = runtimeInput.options[runtimeInput.selectedIndex].text;
  const availabilityLabel = availabilityInput.options[availabilityInput.selectedIndex].text;
  const certificationLabel = certificationInput.options[certificationInput.selectedIndex].text;
  label = `${label} · ${mediaTypeLabel} · ${genreLabel} · ${runtimeLabel} · ${popularityLabel} · ${certificationLabel} · ${availabilityLabel}`;
  document.querySelector("#active-view").textContent = label;
  const range = report.available_candidate_years;
  const universe = report.candidate_universe || report.candidates_considered;
  const tmdbTotal = catalogStatus?.tmdb_daily_export?.eligible_movies;
  document.querySelector("#catalog-range").textContent =
    `Rankable now: ${universe?.toLocaleString() || "unknown"} · ${range.minimum}–${range.maximum}` +
    (tmdbTotal ? ` · TMDB universe synced: ${tmdbTotal.toLocaleString()}` : "");
}

function displayReport(report) {
  updateViewLabel(report);
  renderMetrics(report);
  list.innerHTML = "";
  const recommendations = recommendationFiltered(report.recommendations, availabilityInput, certificationInput, Number(limitInput.value));
  recommendations.forEach((movie) => list.append(renderMovie(movie)));
  if (!recommendations.length) {
    list.innerHTML = `<div class="empty">No recommendations match these filters. Try a broader availability, year, or genre selection.</div>`;
  }
  if (report.unavailable_candidate_details) {
    notice.hidden = false;
    notice.textContent = `${report.unavailable_candidate_details} stale or unavailable catalog records were skipped safely.`;
  }
  lowestList.innerHTML = "";
  const lowestRecommendations = recommendationFiltered(report.lowest_recommendations, availabilityInput, certificationInput);
  lowestRecommendations.forEach((movie, index) => {
    lowestList.append(renderMovie(movie, `LOW ${index + 1}`));
  });
  if (!lowestRecommendations.length) {
    lowestList.innerHTML = `<div class="empty">No lowest-score movies match the selected U.S. availability.</div>`;
  }
}

async function responseJson(response) {
  const body = await response.text();
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(response.ok ? "The server returned an unreadable response." : "The request failed on the server.");
  }
}

function updateProfileSummary() {
  const profile = savedProfiles.find((item) => item.slug === user);
  if (!profile) {
    profileSummary.textContent = "No profiles yet · import one to begin";
    return;
  }
  const attention = profile.pending
    ? ` · ${profile.pending} title${profile.pending === 1 ? "" : "s"} still need catalog attention`
    : " · catalog matching complete";
  profileSummary.textContent = `${profile.rated} rated · ${profile.mapped} mapped${attention}`;
}

function syncProfileEditor() {
  const profile = savedProfiles.find((item) => item.slug === user);
  profileEditor.hidden = !profile;
  emptyProfileState.hidden = Boolean(profile);
  profileDisplayNameInput.value = profile?.display_name || "";
  profileIdInput.value = profile?.slug || user;
  deleteProfileConfirmation.value = "";
  deleteProfileButton.disabled = false;
  updateProfileStatus.textContent = "";
  profileStats.hidden = true;
  profileStats.innerHTML = "";
  statsYearInput.innerHTML = '<option value="">All years</option>';
  profileAccuracy.hidden = true;
  profileAccuracy.innerHTML = "";
  selectedManualMovie = null;
  manualMovieResults.hidden = true;
  manualMovieResults.innerHTML = "";
  manualRatingFields.hidden = true;
  manualMovieRatingInput.value = "3.5";
  manualMovieReviewInput.value = "";
  manualRatingStatus.textContent = "";
  profileEditorStatus.textContent = profile?.ranking_ready
    ? "Ranking is ready. Upload another export under this profile ID to update its movie history."
    : "Profile data is saved, but its ranking should be rebuilt.";
}

function populateProfileSelectors(preferred = null) {
  const previousGroup = groupProfileInputs.map((input) => input.value);
  profileSelect.innerHTML = savedProfiles.length
    ? savedProfiles.map((profile) => `<option value="${escapeHtml(profile.slug)}">${escapeHtml(profile.display_name)}</option>`).join("")
    : '<option value="">No profiles yet</option>';
  if (savedProfiles.some((profile) => profile.slug === preferred)) user = preferred;
  else if (!savedProfiles.some((profile) => profile.slug === user) && savedProfiles.length) user = savedProfiles[0].slug;
  else if (!savedProfiles.length) user = "";
  profileSelect.value = user;
  profileSelect.disabled = !savedProfiles.length;
  manageProfileSelect.innerHTML = profileSelect.innerHTML;
  manageProfileSelect.value = user;
  manageProfileSelect.disabled = !savedProfiles.length;
  profilesEmptyState.hidden = Boolean(savedProfiles.length);
  document.body.dataset.user = user;

  const automaticGroup = [
    ...savedProfiles.filter((profile) => profile.slug === user),
    ...savedProfiles.filter((profile) => profile.slug !== user),
  ].slice(0, 4);
  groupProfileInputs.forEach((input, index) => {
    const optional = index > 1;
    input.innerHTML = `${optional ? '<option value="">Not added</option>' : '<option value="">Choose a profile</option>'}` +
      savedProfiles.map((profile) => `<option value="${escapeHtml(profile.slug)}">${escapeHtml(profile.display_name)}</option>`).join("");
    const fallback = automaticGroup[index]?.slug || "";
    input.value = savedProfiles.some((profile) => profile.slug === previousGroup[index]) ? previousGroup[index] : (fallback || "");
    input.disabled = !savedProfiles.length;
  });
  applyButton.disabled = !savedProfiles.length;
  searchMovieButton.disabled = !savedProfiles.length;
  buildGroupButton.disabled = savedProfiles.length < 2;
  searchGroupMovieButton.disabled = savedProfiles.length < 2;
  updateProfileSummary();
  syncProfileEditor();
}

async function loadProfiles(preferred = null) {
  const response = await fetch("/profiles");
  const result = await responseJson(response);
  if (!response.ok) throw new Error(result.detail || "Could not load saved profiles");
  savedProfiles = result.profiles;
  populateProfileSelectors(preferred);
}

function switchView(view) {
  const selected = ["personal", "group", "profiles"].includes(view) ? view : "personal";
  document.querySelector("#personal-view").hidden = selected !== "personal";
  document.querySelector("#group-view").hidden = selected !== "group";
  document.querySelector("#profiles-view").hidden = selected !== "profiles";
  viewTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === selected));
  const destination = selected === "group" ? "#movie-night" : selected === "profiles" ? "#profiles" : location.pathname;
  history.replaceState(null, "", destination);
}

async function loadRecommendations({ refresh = false } = {}) {
  if (!user) {
    metrics.innerHTML = "";
    list.innerHTML = '<div class="empty">No recommendations yet. Add your first profile above.</div>';
    lowestList.innerHTML = '<div class="empty">This section will appear after a profile is imported.</div>';
    return false;
  }
  applyButton.disabled = true;
  applyButton.textContent = "Loading…";
  list.innerHTML = `<div class="empty">${refresh ? "Rebuilding this person's ranking…" : "Loading recommendations…"}</div>`;
  notice.hidden = true;
  const params = requestParams();
  try {
    const path = refresh
      ? `/recommendations/${encodeURIComponent(user)}/refresh?${params}`
      : `/recommendations/${encodeURIComponent(user)}?scope=all&${params}`;
    const response = await fetch(path, { method: refresh ? "POST" : "GET" });
    const report = await responseJson(response);
    if (!response.ok) throw new Error(report.detail || "Could not load recommendations");
    displayReport(report);
    return true;
  } catch (error) {
    list.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    return false;
  } finally {
    applyButton.disabled = false;
    applyButton.textContent = "Update recommendations";
  }
}

async function saveProfile() {
  const displayName = profileDisplayNameInput.value.trim();
  if (!displayName) {
    profileEditorStatus.textContent = "Enter a display name.";
    return;
  }
  saveProfileButton.disabled = true;
  saveProfileButton.textContent = "Saving…";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName }),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Profile could not be updated");
    await loadProfiles(user);
    profileEditorStatus.textContent = `Display name changed to ${result.display_name}.`;
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    saveProfileButton.disabled = false;
    saveProfileButton.textContent = "Save name";
  }
}

async function showProfileStats() {
  const watchedYear = statsYearInput.value ? Number(statsYearInput.value) : null;
  showProfileStatsButton.disabled = true;
  showProfileStatsButton.textContent = "Loading…";
  try {
    const statsParams = new URLSearchParams();
    if (watchedYear) {
      statsParams.set("watched_year_min", watchedYear);
      statsParams.set("watched_year_max", watchedYear);
    }
    const [response, accuracyResponse] = await Promise.all([
      fetch(`/profiles/${encodeURIComponent(user)}/stats?${statsParams}`),
      fetch(`/profiles/${encodeURIComponent(user)}/accuracy`),
    ]);
    const stats = await responseJson(response);
    if (!response.ok) throw new Error(stats.detail || "Profile statistics could not be loaded");
    const selectedStatsYear = statsYearInput.value;
    statsYearInput.innerHTML = '<option value="">All years</option>' +
      (stats.available_review_years || []).map((year) => `<option value="${year}">${year}</option>`).join("");
    statsYearInput.value = selectedStatsYear;
    const accuracy = await responseJson(accuracyResponse);
    const value = (label, number) => `
      <div class="profile-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(number ?? "—")}</strong></div>`;
    const distribution = Object.entries(stats.rating_distribution)
      .filter(([, count]) => count)
      .map(([rating, count]) => `<span>${rating} ★ · <b>${count}</b></span>`)
      .join("");
    const surpriseList = (label, items) => items?.length ? `
      <div class="prediction-surprise-list">
        <strong>${escapeHtml(label)}</strong>
        ${items.map((item, index) => `<div class="prediction-surprise-row"><span>${index + 1}. ${escapeHtml(item.title)}${item.year ? ` (${item.year})` : ""}</span><small>Rated ${item.actual_rating.toFixed(1)} ★ · expected ${item.expected_rating.toFixed(1)} ★ · <b>${item.difference >= 0 ? "+" : ""}${item.difference.toFixed(1)} ★</b></small></div>`).join("")}
      </div>` : "";
    const surprises = accuracyResponse.ok && accuracy.rating_surprises
      ? `<section class="prediction-surprises">
          <div><strong>Rated movies vs expected</strong><span>These are honest held-out predictions: the movie's rating was hidden while the model made its estimate.</span></div>
          ${surpriseList("Three highest versus expected", accuracy.rating_surprises.highest_actual_minus_expected_top3 || [accuracy.rating_surprises.highest_actual_minus_expected])}
          ${surpriseList("Three lowest versus expected", accuracy.rating_surprises.lowest_actual_minus_expected_top3 || [accuracy.rating_surprises.lowest_actual_minus_expected])}
        </section>`
      : `<section class="prediction-surprises"><div><strong>Rated movies vs expected</strong><span>${escapeHtml(accuracy.detail || "At least ten model-linked ratings are needed for an honest held-out comparison.")}</span></div></section>`;
    const taste = stats.taste_breakdown || {};
    const tasteRows = (heading, category, items) => items?.length ? `
      <section class="taste-stat-card">
        <button type="button" class="taste-category-button" data-category="${escapeHtml(category)}" data-heading="${escapeHtml(heading)}"><span>${escapeHtml(heading)}</span><small>View up to 25 highest and 25 lowest</small></button>
        ${items.map((item) => `<button type="button" class="taste-stat-row" data-category="${escapeHtml(category)}" data-value="${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}<small>${item.films} rated film${item.films === 1 ? "" : "s"} · view movies</small></span><strong>${item.expected_rating.toFixed(2)} ★<small>${item.difference_from_profile >= 0 ? "+" : ""}${item.difference_from_profile.toFixed(2)} vs usual</small></strong></button>`).join("")}
      </section>` : "";
    const tasteBreakdown = taste.explanation ? `
      <section class="taste-breakdown">
        <div class="taste-breakdown-heading"><strong>Your taste, feature by feature</strong><span>${escapeHtml(taste.explanation)}</span></div>
        <div class="taste-stat-grid">
          ${tasteRows("Genres", "genres", taste.genres)}
          ${tasteRows("Themes", "themes", taste.themes)}
          ${tasteRows("Decades", "decades", taste.decades)}
          ${tasteRows("Directors", "directors", taste.directors)}
          ${tasteRows("Actors", "actors", taste.actors)}
          ${tasteRows("Languages", "languages", taste.languages)}
          ${tasteRows("Production countries", "countries", taste.countries)}
          ${tasteRows("Runtime", "runtimes", taste.runtimes)}
          ${tasteRows("Movie popularity", "popularity", taste.popularity)}
          ${tasteRows("US content ratings", "certifications", taste.certifications)}
        </div>
      </section>` : "";
    const facts = taste.fun_facts || {};
    const filterLabel = watchedYear
      ? `${watchedYear} diary entries`
      : "All diary years";
    profileStats.innerHTML = [
      `<div class="stats-scope"><strong>${escapeHtml(filterLabel)}</strong><span>${stats.rated_films} rating${stats.rated_films === 1 ? "" : "s"} included.${stats.undated_ratings_excluded ? ` ${stats.undated_ratings_excluded} rating${stats.undated_ratings_excluded === 1 ? "" : "s"} without a diary date excluded.` : ""} Prediction-surprise and model-accuracy results remain all-time.</span></div>`,
      value("Rated films", stats.rated_films),
      value("Average rating", stats.average_rating?.toFixed(2)),
      value("Median rating", stats.median_rating?.toFixed(2)),
      value("Rating range", stats.lowest_rating == null ? null : `${stats.lowest_rating}–${stats.highest_rating}`),
      value("Rated reviews", stats.rated_reviews),
      value("Rewatches", stats.rewatches),
      value("Mapped", stats.mapped_films),
      value("Needs mapping", stats.pending_films),
      value("Rating spread", facts.rating_spread == null ? null : `${facts.rating_spread.toFixed(2)} ★`),
      value("Five-star films", facts.five_star_films),
      value("2 stars or lower", facts.two_stars_or_lower),
      value("Genres explored", facts.genres_explored),
      value("Decades explored", facts.decades_explored),
      value("Languages explored", facts.languages_explored),
      value("Production countries explored", facts.countries_explored),
      value(
        "US content ratings found",
        facts.certification_coverage_percent == null
          ? null
          : `${facts.certification_known_films} films · ${facts.certification_coverage_percent}%`,
      ),
      value("Content rating unknown", facts.certification_unknown_films),
      stats.rewatched_titles?.length
        ? `<div class="rewatch-audit"><span><b>Rewatches counted from Letterboxd diary</b></span>${stats.rewatched_titles.map((item) => `<span>${escapeHtml(item.title)} · <b>${item.count}</b></span>`).join("")}</div>`
        : `<div class="rewatch-audit"><span>No diary entries were marked as rewatches.</span></div>`,
      `<div class="rating-distribution"><span><b>Rating distribution</b></span>${distribution || "No ratings"}</div>`,
      surprises,
      tasteBreakdown,
    ].join("");
    profileStats.hidden = false;
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    showProfileStatsButton.disabled = false;
    showProfileStatsButton.textContent = "View stats";
  }
}

async function showStatMovies(category, value, { returnToCategory = false } = {}) {
  closeStatMoviesButton.textContent = returnToCategory ? "Back" : "Close";
  statMoviesTitle.textContent = value;
  statMoviesSummary.textContent = "Loading the movies behind this statistic…";
  statMoviesList.innerHTML = "";
  statMoviesDialog.showModal();
  try {
    const params = new URLSearchParams({ category, value });
    if (statsYearInput.value) params.set("watched_year", statsYearInput.value);
    const response = await fetch(
      `/profiles/${encodeURIComponent(user)}/stats/movies?${params}`,
    );
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Statistic movies could not be loaded");
    statMoviesSummary.textContent = `${result.count} unique rated movie${result.count === 1 ? "" : "s"}${result.watched_year ? ` watched in ${result.watched_year}` : " across all diary years"}.`;
    statMoviesList.innerHTML = result.movies.length
      ? result.movies.map((item) => `
          <article class="rating-history-row">
            ${item.poster_url ? `<img src="${escapeHtml(item.poster_url)}" alt="" loading="lazy" />` : '<span class="rating-history-poster-placeholder"></span>'}
            <div class="rating-history-copy">
              <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.year ?? "Year unavailable")}${item.watched_date ? ` · watched ${escapeHtml(item.watched_date)}` : ""}</span></div>
              ${item.review_text ? `<p>${escapeHtml(item.review_text)}</p>` : ""}
            </div>
            <div class="rating-history-score"><strong>${item.rating.toFixed(1)}</strong><span>★ / 5</span></div>
          </article>`).join("")
      : '<div class="empty">No rated movies match this statistic.</div>';
  } catch (error) {
    statMoviesSummary.textContent = error.message;
  }
}

async function showStatCategory(category, heading) {
  statCategoryTitle.textContent = heading;
  statCategorySummary.textContent = "Loading this profile's strongest and weakest matches…";
  statCategoryTop.innerHTML = "";
  statCategoryBottom.innerHTML = "";
  statCategoryDialog.showModal();
  try {
    const params = new URLSearchParams({ category });
    if (statsYearInput.value) params.set("watched_year", statsYearInput.value);
    const response = await fetch(
      `/profiles/${encodeURIComponent(user)}/stats/category?${params}`,
    );
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Taste category could not be loaded");
    statCategorySummary.textContent = `${result.count} ${heading.toLowerCase()} with rating evidence${result.watched_year ? ` from ${result.watched_year} diary entries` : " across all diary years"}. Click any item to see its movies.`;
    const rows = (items) => items.length
      ? items.map((item, index) => `<button type="button" class="stat-category-row" data-category="${escapeHtml(category)}" data-value="${escapeHtml(item.label)}"><span><b>${index + 1}. ${escapeHtml(item.label)}</b><small>${item.films} rated film${item.films === 1 ? "" : "s"}</small></span><strong>${item.expected_rating.toFixed(2)} ★<small>${item.difference_from_profile >= 0 ? "+" : ""}${item.difference_from_profile.toFixed(2)} vs usual</small></strong></button>`).join("")
      : '<div class="empty compact-empty">Not enough distinct items for this side.</div>';
    statCategoryTop.innerHTML = rows(result.top || []);
    statCategoryBottom.innerHTML = rows(result.bottom || []);
  } catch (error) {
    statCategorySummary.textContent = error.message;
  }
}

async function showProfileRatings() {
  showProfileRatingsButton.disabled = true;
  showProfileRatingsButton.textContent = "Loading…";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}/ratings`);
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Rating history could not be loaded");
    ratingHistoryTitle.textContent = `${result.display_name}'s rated movies`;
    ratingHistorySummary.textContent = `${result.count} rated film${result.count === 1 ? "" : "s"} · most recent watches first`;
    ratingHistoryList.innerHTML = result.ratings.length
      ? result.ratings.map((item) => `
          <article class="rating-history-row">
            ${item.poster_url ? `<img src="${escapeHtml(item.poster_url)}" alt="" loading="lazy" />` : '<span class="rating-history-poster-placeholder"></span>'}
            <div class="rating-history-copy">
              <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.year ?? "Year unavailable")}${item.watched_date ? ` · watched ${escapeHtml(item.watched_date)}` : ""}</span></div>
              ${item.review_text ? `<p>${escapeHtml(item.review_text)}</p>` : ""}
            </div>
            <div class="rating-history-score"><strong>${item.rating.toFixed(1)}</strong><span>★ / 5</span>${item.rewatch_count ? `<small>${item.rewatch_count} rewatch${item.rewatch_count === 1 ? "" : "es"}</small>` : ""}</div>
            <button class="rating-history-delete" type="button" data-movie-id="${item.movie_id}" data-movie-title="${escapeHtml(item.title)}">Delete</button>
          </article>`).join("")
      : '<div class="empty">No rated movies are saved for this profile.</div>';
    ratingHistoryDialog.showModal();
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    showProfileRatingsButton.disabled = false;
    showProfileRatingsButton.textContent = "Rating history";
  }
}

async function deleteRating(event) {
  const button = event.target.closest(".rating-history-delete");
  if (!button) return;
  const title = button.dataset.movieTitle;
  if (!window.confirm(`Delete ${title} from this profile's rating history? This cannot be undone.`)) return;
  button.disabled = true;
  button.textContent = "Deleting…";
  try {
    const response = await fetch(
      `/profiles/${encodeURIComponent(user)}/ratings/${encodeURIComponent(button.dataset.movieId)}`,
      { method: "DELETE" },
    );
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Rating could not be deleted");
    await loadProfiles(user);
    await loadRecommendations();
    await showProfileRatings();
    ratingHistorySummary.textContent = `${result.title} was deleted. ${ratingHistorySummary.textContent}`;
  } catch (error) {
    ratingHistorySummary.textContent = error.message;
    button.disabled = false;
    button.textContent = "Delete";
  }
}

async function showProfileAccuracy() {
  showProfileAccuracyButton.disabled = true;
  showProfileAccuracyButton.textContent = "Testing…";
  profileEditorStatus.textContent = "Running five held-out tests. The test films are hidden while each personal model is fitted.";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}/accuracy`);
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Model accuracy could not be measured");
    const modelRows = result.models.map((item) => `
      <tr><td>${escapeHtml(item.model)}</td><td>${item.mae.toFixed(2)} ★</td><td>${item.rmse.toFixed(2)} ★</td></tr>`).join("");
    const calibrationRows = result.calibration.map((item) => `
      <tr><td>${escapeHtml(item.band)}</td><td>${item.predicted_average.toFixed(2)}</td><td>${item.actual_average.toFixed(2)}</td><td>${item.samples}</td></tr>`).join("");
    const weights = result.personalized_weights?.weights;
    const coldWeights = result.personalized_weights?.cold_start_weights;
    const weightSummary = weights
      ? `${Math.round(weights.collaborative * 100)}% collaborative · ${Math.round(weights.content * 100)}% metadata · ${Math.round(weights.popularity * 100)}% popularity`
      : "Default blend";
    const coldWeightSummary = coldWeights
      ? `${Math.round(coldWeights.metadata * 100)}% metadata · ${Math.round(coldWeights.public_rating * 100)}% public-rating prior`
      : "Default new-title blend";
    const reviewPolicy = result.review_signal_policy || {};
    const reviewSummary = reviewPolicy.enabled
      ? `Included at ${Number(reviewPolicy.selected_scale || 0).toFixed(2)} strength because it improved held-out accuracy.`
      : `Weight 0 — ${reviewPolicy.reason || "review commentary has not shown reliable predictive value for this profile"}`;
    profileAccuracy.innerHTML = `
      <div class="accuracy-intro"><strong>How well does this profile predict ratings it has not trained on?</strong><span>${escapeHtml(result.method)} · ${result.linked_ratings} evaluation-ready ratings · ${escapeHtml(result.reliability)} evidence</span></div>
      <p class="weight-summary"><b>Automatically selected catalog blend:</b> ${escapeHtml(weightSummary)}<br /><b>New and unlinked titles:</b> ${escapeHtml(coldWeightSummary)}</p>
      <div class="signal-glossary">
        <strong>What the rating components mean</strong>
        <p><b>Collaborative:</b> what MovieLens viewers with similar rating patterns tended to score the movie.</p>
        <p><b>Metadata:</b> this profile's learned response to genres, themes and synopsis terms, director, cast, decade, and original language.</p>
        <p><b>MovieLens audience prior:</b> the movie's public MovieLens average, stabilized so a tiny number of ratings cannot dominate.</p>
        <p><b>New-title public-rating prior:</b> TMDB's public score converted to 0.5–5 and pulled toward this person's average when the vote count is small.</p>
        <p><b>Written-review commentary:</b> ${escapeHtml(reviewSummary)}</p>
      </div>
      <div class="accuracy-highlights">
        <div><span>Typical error</span><strong>${result.mae.toFixed(2)} ★</strong></div>
        <div><span>Within ½ star</span><strong>${result.within_half_star.toFixed(1)}%</strong></div>
        <div><span>Bias</span><strong>${escapeHtml(result.bias_label)}</strong><small>${result.bias >= 0 ? "+" : ""}${result.bias.toFixed(2)} ★</small></div>
        <div><span>Held-out predictions</span><strong>${result.test_predictions}</strong></div>
      </div>
      <div class="accuracy-tables">
        <table><caption>Model comparison</caption><thead><tr><th>Model</th><th>MAE</th><th>RMSE</th></tr></thead><tbody>${modelRows}</tbody></table>
        <table><caption>Calibration by predicted range</caption><thead><tr><th>Range</th><th>Predicted</th><th>Actual</th><th>N</th></tr></thead><tbody>${calibrationRows}</tbody></table>
      </div>
      <p class="accuracy-note">Lower error is better. Repeating the split five times makes this more stable than judging the model from a single test.</p>`;
    profileAccuracy.hidden = false;
    profileEditorStatus.textContent = "Accuracy check complete.";
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    showProfileAccuracyButton.disabled = false;
    showProfileAccuracyButton.textContent = "Model accuracy";
  }
}

async function exportProfile() {
  exportProfileButton.disabled = true;
  exportProfileButton.textContent = "Preparing…";
  profileEditorStatus.textContent = "Preparing a portable, rating-only profile backup.";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}/export`);
    if (!response.ok) {
      const result = await responseJson(response);
      throw new Error(result.detail || "Profile could not be exported");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || `movie-compass-${user}.zip`;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    profileEditorStatus.textContent = `${filename} downloaded. Import this ZIP on another Movie Compass installation.`;
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    exportProfileButton.disabled = false;
    exportProfileButton.textContent = "Download profile";
  }
}

function chooseManualMovie(movie) {
  selectedManualMovie = movie;
  const mediaLabel = movie.media_type === "tv" ? "Miniseries / TV" : "Movie";
  selectedManualMovieLabel.textContent = `${movie.title}${movie.year ? ` (${movie.year})` : ""} · ${mediaLabel}`;
  manualMovieRatingInput.value = movie.current_rating?.toString() || "3.5";
  manualMovieReviewInput.value = movie.current_review_text || "";
  manualRatingFields.hidden = false;
  manualRatingStatus.textContent = movie.current_rating
    ? `Existing ${movie.current_rating.toFixed(1)}-star rating loaded. Saving will replace it and date the entry today.`
    : "Movie selected. Saving will date this rating today; a written review is optional.";
}

async function findManualMovie() {
  const query = manualMovieQueryInput.value.trim();
  if (query.length < 2) {
    manualRatingStatus.textContent = "Enter at least two characters of the movie title.";
    return;
  }
  findManualMovieButton.disabled = true;
  findManualMovieButton.textContent = "Searching…";
  manualRatingStatus.textContent = "Finding the exact TMDB title…";
  manualMovieResults.innerHTML = "";
  try {
    const params = new URLSearchParams({ q: query, user });
    if (manualMovieYearInput.value) params.set("year", manualMovieYearInput.value);
    const response = await fetch(`/movies/rating-search?${params}`);
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Movie search failed");
    result.results.forEach((movie) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "manual-movie-option";
      const mediaLabel = movie.media_type === "tv" ? "Miniseries / TV" : "Movie";
      const adultLabel = movie.adult ? " · Adult title" : "";
      option.innerHTML = `${manualPosterMarkup(movie)}<span><b>${escapeHtml(movie.title)}</b><small>${escapeHtml(movie.year ?? "Year unavailable")} · ${mediaLabel}${adultLabel}</small></span>`;
      enableSensitivePosterReveal(option);
      option.addEventListener("click", () => chooseManualMovie(movie));
      manualMovieResults.append(option);
    });
    manualMovieResults.hidden = !result.results.length;
    manualRatingStatus.textContent = result.results.length
      ? `${result.warning ? `${result.warning} ` : ""}Choose the correct title below.`
      : `No TMDB titles matched “${query}”.`;
  } catch (error) {
    manualRatingStatus.textContent = error.message;
  } finally {
    findManualMovieButton.disabled = false;
    findManualMovieButton.textContent = "Find movie";
  }
}

async function saveManualRating() {
  if (!selectedManualMovie) {
    manualRatingStatus.textContent = "Search for and select the movie first.";
    return;
  }
  saveManualRatingButton.disabled = true;
  saveManualRatingButton.textContent = "Saving & rebuilding…";
  manualRatingStatus.textContent = "Saving this rating and updating the personal model…";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}/ratings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...selectedManualMovie,
        rating: Number(manualMovieRatingInput.value),
        review_text: manualMovieReviewInput.value.trim() || null,
      }),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Rating could not be saved");
    const savedTitle = result.title;
    const savedRating = result.rating;
    await loadProfiles(user);
    await loadRecommendations();
    manualRatingStatus.textContent = result.ranking_updated
      ? `${savedTitle} was saved at ${savedRating.toFixed(1)} stars with today's date. Recommendations and personalized weights were updated.${result.details_warning ? ` ${result.details_warning}` : ""}`
      : result.ranking_warning;
  } catch (error) {
    manualRatingStatus.textContent = error.message;
  } finally {
    saveManualRatingButton.disabled = false;
    saveManualRatingButton.textContent = "Save rating";
  }
}

async function rebuildProfile() {
  rebuildProfileButton.disabled = true;
  rebuildProfileButton.textContent = "Rebuilding…";
  profileEditorStatus.textContent = "Rebuilding this profile's recommendations.";
  const ready = await loadRecommendations({ refresh: true });
  await loadProfiles(user);
  profileEditorStatus.textContent = ready
    ? "Ranking rebuilt successfully."
    : "The profile is saved, but its ranking could not be rebuilt.";
  rebuildProfileButton.disabled = false;
  rebuildProfileButton.textContent = "Rebuild ranking";
}

async function deleteProfile() {
  const confirmation = deleteProfileConfirmation.value.trim();
  const profile = savedProfiles.find((item) => item.slug === user);
  if (![user, profile?.display_name].includes(confirmation)) {
    profileEditorStatus.textContent = `Type ${profile?.display_name || user} or ${user} exactly to confirm deletion.`;
    return;
  }
  const deletedUser = user;
  deleteProfileButton.disabled = true;
  deleteProfileButton.textContent = "Deleting…";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(deletedUser)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation }),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Profile could not be deleted");
    await loadProfiles();
    localStorage.setItem("movie-compass-profile", user);
    await loadRecommendations();
    profileEditorStatus.textContent = result.warnings?.length
      ? `Profile deleted. ${result.warnings.join(" ")}`
      : `${deletedUser} was deleted permanently.`;
  } catch (error) {
    profileEditorStatus.textContent = error.message;
    deleteProfileButton.disabled = false;
  } finally {
    deleteProfileButton.textContent = "Delete permanently";
  }
}

async function searchMovieScores() {
  const query = movieQueryInput.value.trim();
  if (query.length < 2) {
    searchStatus.textContent = "Enter at least two characters.";
    return;
  }
  searchMovieButton.disabled = true;
  searchMovieButton.textContent = "Scoring…";
  const searchYear = movieSearchYearInput.value;
  searchStatus.textContent = `Searching TMDB for “${query}”${searchYear ? ` from ${searchYear}` : ""}…`;
  searchResults.innerHTML = "";
  try {
    const params = new URLSearchParams({ q: query, limit: "10", country: "US" });
    if (searchYear) params.set("year", searchYear);
    const response = await fetch(`/movies/search/${encodeURIComponent(user)}?${params}`);
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Movie lookup failed");
    searchStatus.textContent = result.results.length
      ? `${result.matches_scored} matching title${result.matches_scored === 1 ? "" : "s"} scored for ${user}.`
      : `No TMDB titles matched “${query}”${searchYear ? ` from ${searchYear}` : ""}.`;
    result.results.forEach((movie) => searchResults.append(renderMovie(movie)));
  } catch (error) {
    searchStatus.textContent = error.message;
  } finally {
    searchMovieButton.disabled = false;
    searchMovieButton.textContent = "Find expected score";
  }
}

async function loadCatalogStatus() {
  try {
    const response = await fetch("/catalog/status");
    catalogStatus = await responseJson(response);
  } catch {
    catalogStatus = null;
  }
}

async function buildGroupRecommendations() {
  const users = groupProfileInputs.map((input) => input.value.trim()).filter(Boolean);
  if (users.length < 2 || users.length > 4) {
    groupStatus.textContent = "Enter two to four imported profile names.";
    return;
  }
  if (new Set(users).size !== users.length) {
    groupStatus.textContent = "Each person needs a different profile.";
    return;
  }
  buildGroupButton.disabled = true;
  buildGroupButton.textContent = "Balancing tastes…";
  groupStatus.textContent = "Scoring a shared candidate set for every person. This can take a little while.";
  groupResults.innerHTML = "";
  groupLowestResults.innerHTML = "";
  groupLowestHeading.hidden = true;
  groupDivisiveResults.innerHTML = "";
  groupDivisiveHeading.hidden = true;
  const startedAt = performance.now();
  const [runtimeMinimum, runtimeMaximum] = runtimeBounds(groupRuntimeInput);
  const body = {
    users,
    limit: groupAvailabilityInput.value === "all" && groupCertificationInput.value === "all" ? Number(groupLimitInput.value) : 30,
    popularity: groupPopularityInput.value,
    media_type: groupMediaTypeInput.value,
    genre: groupGenreInput.value || null,
    include_watched: groupIncludeWatchedInput.checked,
    year_min: groupYearMinInput.value ? Number(groupYearMinInput.value) : null,
    year_max: groupYearMaxInput.value ? Number(groupYearMaxInput.value) : null,
    runtime_min: runtimeMinimum,
    runtime_max: runtimeMaximum,
    country: "US",
  };
  try {
    const response = await fetch("/groups/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Group ranking failed");
    const screened = Number(result.catalog_candidates_screened || 0);
    const screenMessage = screened
      ? `Each profile screened ${screened.toLocaleString()} movies matching these filters. `
      : "Each profile screened the available catalog. ";
    groupStatus.textContent =
      screenMessage +
      `${result.candidate_union.toLocaleString()} strongest and weakest finalists across the profiles were compared head-to-head; ${result.eligible_for_everyone.toLocaleString()} had a usable score for everyone. ` +
      `Ranked in ${((performance.now() - startedAt) / 1000).toFixed(1)} seconds. ` +
      "The group score rewards a strong average while protecting the least enthusiastic person." +
      (result.include_watched
        ? " Movies seen by the whole group are included."
        : " Movies everyone has already seen are hidden; partially watched choices remain eligible.");
    const groupRecommendations = recommendationFiltered(result.recommendations, groupAvailabilityInput, groupCertificationInput, Number(groupLimitInput.value));
    groupRecommendations.forEach((movie) => groupResults.append(renderMovie(movie)));
    if (!groupRecommendations.length) {
      groupResults.innerHTML = `<div class="empty">No shared movies matched these filters and the selected U.S. availability.</div>`;
    }
    const groupLowest = recommendationFiltered(result.lowest_recommendations, groupAvailabilityInput, groupCertificationInput);
    groupLowest.forEach((movie, index) => {
      groupLowestResults.append(renderMovie(movie, `LOW ${index + 1}`));
    });
    groupLowestHeading.hidden = !groupLowest.length;
    const groupDivisive = recommendationFiltered(result.most_divisive, groupAvailabilityInput, groupCertificationInput);
    groupDivisive.forEach((movie, index) => {
      const personSection = document.createElement("section");
      personSection.className = "person-split";
      const personName = movie.featured_enthusiast_display_name || `Person ${index + 1}`;
      personSection.innerHTML = `<div class="person-split-heading"><strong>${escapeHtml(personName)}'s split</strong><span>${escapeHtml(movie.featured_enthusiasm_label || "best available contrast")}</span></div>`;
      personSection.append(renderMovie(movie, "SPLIT"));
      groupDivisiveResults.append(personSection);
    });
    groupDivisiveHeading.hidden = !groupDivisive.length;
  } catch (error) {
    groupStatus.textContent = error.message;
  } finally {
    buildGroupButton.disabled = false;
    buildGroupButton.textContent = "Find a group movie";
  }
}

async function searchGroupMovieScores() {
  const users = groupProfileInputs.map((input) => input.value.trim()).filter(Boolean);
  const query = groupMovieQueryInput.value.trim();
  const searchYear = groupMovieSearchYearInput.value;
  if (users.length < 2 || users.length > 4 || new Set(users).size !== users.length) {
    groupSearchStatus.textContent = "Choose two to four different saved profiles first.";
    return;
  }
  if (query.length < 2) {
    groupSearchStatus.textContent = "Enter at least two characters.";
    return;
  }
  searchGroupMovieButton.disabled = true;
  searchGroupMovieButton.textContent = "Scoring…";
  groupSearchStatus.textContent = `Searching TMDB for “${query}”${searchYear ? ` from ${searchYear}` : ""}, then checking everyone's taste…`;
  groupSearchResults.innerHTML = "";
  try {
    const response = await fetch("/groups/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        users,
        query,
        year: searchYear ? Number(searchYear) : null,
        limit: 10,
        country: "US",
      }),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Group movie lookup failed");
    groupSearchStatus.textContent = result.recommendations.length
      ? `${result.recommendations.length} matching title${result.recommendations.length === 1 ? "" : "s"} scored for everyone.`
      : `No TMDB title matched “${query}”${searchYear ? ` from ${searchYear}` : ""}.`;
    result.recommendations.forEach((movie) => groupSearchResults.append(renderMovie(movie)));
  } catch (error) {
    groupSearchStatus.textContent = error.message;
  } finally {
    searchGroupMovieButton.disabled = false;
    searchGroupMovieButton.textContent = "Score for the group";
  }
}

async function importArchive(slug, archive, button, status, idleLabel) {
  if (!/^[A-Za-z0-9_-]+$/.test(slug)) {
    status.textContent = "Profile ID may contain only letters, numbers, - and _.";
    return false;
  }
  if (!archive) {
    status.textContent = "Choose a Letterboxd ZIP export first.";
    return false;
  }
  button.disabled = true;
  button.textContent = "Importing…";
  status.textContent = "Reading rated films and mapping them to TMDB. This can take a minute.";
  const form = new FormData();
  form.set("user", slug);
  form.set("archive", archive);
  try {
    const response = await fetch("/profiles/import", { method: "POST", body: form });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Import failed");
    user = slug;
    document.body.dataset.user = slug;
    status.textContent = `Imported ${result.import.movies_staged} rated films. Building this profile's ranking now…`;
    await loadProfiles(slug);
    const rankingReady = await loadRecommendations({ refresh: true });
    const saved = savedProfiles.find((profile) => profile.slug === slug);
    const mappingSummary = saved
      ? `${saved.mapped} of ${saved.films} titles are matched${saved.pending ? `; automatic matching could not resolve ${saved.pending}` : ""}. `
      : "";
    status.textContent = rankingReady
      ? `Profile saved and ranking ready. ${mappingSummary}` +
        (result.mapping_warning || "TMDB connection completed successfully.")
      : `Profile saved. ${mappingSummary}The ranking build needs to be retried with Update recommendations.`;
    return true;
  } catch (error) {
    status.textContent = error.message;
    return false;
  } finally {
    button.disabled = false;
    button.textContent = idleLabel;
  }
}

async function importProfile() {
  const slug = profileNameInput.value.trim();
  if (savedProfiles.some((profile) => profile.slug.toLowerCase() === slug.toLowerCase())) {
    importStatus.textContent = "That profile ID already exists. Update it from Manage profile.";
    return;
  }
  const completed = await importArchive(
    slug,
    profileArchiveInput.files[0],
    importButton,
    importStatus,
    "Create profile",
  );
  if (completed) {
    profileNameInput.value = "";
    profileArchiveInput.value = "";
  }
}

async function updateCurrentProfile() {
  const completed = await importArchive(
    user,
    updateProfileArchiveInput.files[0],
    updateProfileButton,
    updateProfileStatus,
    "Update profile",
  );
  if (completed) updateProfileArchiveInput.value = "";
}

applyButton.addEventListener("click", () => loadRecommendations({ refresh: true }));
importButton.addEventListener("click", importProfile);
saveProfileButton.addEventListener("click", saveProfile);
rebuildProfileButton.addEventListener("click", rebuildProfile);
showProfileStatsButton.addEventListener("click", showProfileStats);
statsYearInput.addEventListener("change", showProfileStats);
profileStats.addEventListener("click", (event) => {
  const category = event.target.closest(".taste-category-button");
  if (category) {
    showStatCategory(category.dataset.category, category.dataset.heading);
    return;
  }
  const row = event.target.closest(".taste-stat-row");
  if (row) showStatMovies(row.dataset.category, row.dataset.value);
});
showProfileRatingsButton.addEventListener("click", showProfileRatings);
closeRatingHistoryButton.addEventListener("click", () => ratingHistoryDialog.close());
ratingHistoryList.addEventListener("click", deleteRating);
ratingHistoryDialog.addEventListener("click", (event) => {
  if (event.target === ratingHistoryDialog) ratingHistoryDialog.close();
});
closeStatMoviesButton.addEventListener("click", () => statMoviesDialog.close());
statMoviesDialog.addEventListener("click", (event) => {
  if (event.target === statMoviesDialog) statMoviesDialog.close();
});
closeStatCategoryButton.addEventListener("click", () => statCategoryDialog.close());
statCategoryDialog.addEventListener("click", (event) => {
  if (event.target === statCategoryDialog) statCategoryDialog.close();
  const row = event.target.closest(".stat-category-row");
  if (row) {
    showStatMovies(row.dataset.category, row.dataset.value, { returnToCategory: true });
  }
});
showProfileAccuracyButton.addEventListener("click", showProfileAccuracy);
exportProfileButton.addEventListener("click", exportProfile);
findManualMovieButton.addEventListener("click", findManualMovie);
saveManualRatingButton.addEventListener("click", saveManualRating);
showAdultPostersInput.addEventListener("change", () => applyAdultPosterPreference(showAdultPostersInput.checked));
updateProfileButton.addEventListener("click", updateCurrentProfile);
deleteProfileButton.addEventListener("click", deleteProfile);
searchMovieButton.addEventListener("click", searchMovieScores);
buildGroupButton.addEventListener("click", buildGroupRecommendations);
searchGroupMovieButton.addEventListener("click", searchGroupMovieScores);
profileSelect.addEventListener("change", () => {
  user = profileSelect.value;
  document.body.dataset.user = user;
  localStorage.setItem("movie-compass-profile", user);
  searchStatus.textContent = "";
  searchResults.innerHTML = "";
  updateProfileSummary();
  syncProfileEditor();
  loadRecommendations();
});
manageProfileSelect.addEventListener("change", () => {
  user = manageProfileSelect.value;
  profileSelect.value = user;
  document.body.dataset.user = user;
  localStorage.setItem("movie-compass-profile", user);
  updateProfileSummary();
  syncProfileEditor();
  loadRecommendations();
});
viewTabs.forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
movieQueryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMovieScores();
});
manualMovieQueryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") findManualMovie();
});
groupMovieQueryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchGroupMovieScores();
});
const preferredProfile = localStorage.getItem("movie-compass-profile") || user;
applyAdultPosterPreference(localStorage.getItem(adultPosterPreferenceKey) === "true");
loadTmdbStatus();
Promise.all([loadCatalogStatus(), loadProfiles(preferredProfile)])
  .then(() => loadRecommendations())
  .catch((error) => {
    list.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  });
switchView(location.hash === "#movie-night" ? "group" : location.hash === "#profiles" ? "profiles" : "personal");
