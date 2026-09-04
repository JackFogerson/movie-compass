let user = document.body.dataset.user;
const yearMinInput = document.querySelector("#year-min");
const yearMaxInput = document.querySelector("#year-max");
const limitInput = document.querySelector("#limit");
const popularityInput = document.querySelector("#popularity");
const genreInput = document.querySelector("#genre");
const runtimeInput = document.querySelector("#runtime");
const countryInput = document.querySelector("#country");
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
const profileStats = document.querySelector("#profile-stats");
const showProfileAccuracyButton = document.querySelector("#show-profile-accuracy");
const exportProfileButton = document.querySelector("#export-profile");
const profileAccuracy = document.querySelector("#profile-accuracy");
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
const emptyProfileState = document.querySelector("#empty-profile-state");
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
const groupGenreInput = document.querySelector("#group-genre");
const groupRuntimeInput = document.querySelector("#group-runtime");
const groupCountryInput = document.querySelector("#group-country");
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
let catalogStatus = null;
let savedProfiles = [];
let selectedManualMovie = null;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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
    ["Popularity prior", movie.popularity_score],
    ["Audience ratings", movie.audience_evidence_count?.toLocaleString()],
    ["TMDB votes", movie.tmdb_vote_count?.toLocaleString()],
  ];
  return values
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([label, value]) => `<span><b>${label}:</b> ${value}</span>`)
    .join("");
}

function runtimeBounds(input) {
  if (!input.value) return [null, null];
  const [minimum, maximum] = input.value.split("-").map(Number);
  return [minimum, maximum];
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
  card.querySelector(".expected-rating").textContent = movie.expected_rating.toFixed(2);
  const uncertainty = movie.rating_uncertainty;
  const isGroup = Array.isArray(movie.individual_scores);
  card.querySelector(".rating-label").textContent = isGroup ? "GROUP FIT" : "EXPECTED";
  card.querySelector(".plausible-range").textContent = isGroup
    ? `Individual range: ${movie.group_minimum.toFixed(1)}–${Math.max(...movie.individual_scores.map((item) => item.expected_rating)).toFixed(1)}`
    : uncertainty?.plausible_minimum != null
      ? `${Math.round(uncertainty.coverage * 100)}% plausible: ${uncertainty.plausible_minimum.toFixed(1)}–${uncertainty.plausible_maximum.toFixed(1)}`
      : "Uncertainty not calibrated";
  const expectation = movie.ranking_expectation;
  const badges = [
    `<span class="badge popularity">${escapeHtml((movie.popularity_tier || "unclassified").replaceAll("_", " "))}</span>`,
    ...movie.genres.map((genre) => `<span class="badge">${escapeHtml(genre)}</span>`),
  ];
  if (movie.runtime) {
    badges.push(`<span class="badge runtime">${escapeHtml(movie.runtime_label || `${movie.runtime} min`)}</span>`);
  }
  (movie.moods || []).forEach((mood) => badges.push(`<span class="badge mood">${escapeHtml(mood)}</span>`));
  if (isGroup && movie.watched_by?.length) {
    badges.push(`<span class="badge rewatch">Seen by ${movie.watched_by.length}/${movie.individual_scores.length}</span>`);
  }
  card.querySelector(".badges").innerHTML = badges.join("");
  card.querySelector(".streaming-info").innerHTML = renderStreaming(movie);
  card.querySelector(".expectation-reason").textContent = isGroup
    ? movie.group_reason
    : expectation.reason;
  const groupScores = card.querySelector(".group-scores");
  if (isGroup) {
    groupScores.innerHTML = movie.individual_scores.map((item) => `
      <div class="group-score-person">
        <b>${escapeHtml(item.display_name || item.user)}</b> · <strong>${item.expected_rating.toFixed(2)}</strong>
        <span>${item.plausible_minimum.toFixed(1)}–${item.plausible_maximum.toFixed(1)} plausible</span>
        <span>${escapeHtml(item.reason)}</span>
      </div>`).join("");
  } else {
    groupScores.remove();
  }
  const explanationList = card.querySelector(".explanations");
  const extraExplanations = movie.why_you_may_like_it || movie.explanation?.slice(1) || [];
  if (extraExplanations.length) {
    explanationList.innerHTML = extraExplanations
      .map((value) => `<li>${escapeHtml(value)}</li>`)
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
      .map((value) => `<li>${escapeHtml(value)}</li>`)
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
  metrics.innerHTML = [
    metric("Source candidates", coverage.candidates_considered),
    metric("Genre diversity", diversity.intra_list_genre_diversity.toFixed(2)),
    metric("Unique genres", diversity.unique_genres),
    metric("Decades represented", diversity.distinct_decades),
  ].join("");
}

function requestParams() {
  const params = new URLSearchParams({
    limit: limitInput.value,
    popularity: popularityInput.value,
  });
  if (yearMinInput.value) params.set("year_min", yearMinInput.value);
  if (yearMaxInput.value) params.set("year_max", yearMaxInput.value);
  if (genreInput.value) params.set("genre", genreInput.value);
  const [runtimeMinimum, runtimeMaximum] = runtimeBounds(runtimeInput);
  if (runtimeMinimum) params.set("runtime_min", runtimeMinimum);
  if (runtimeMaximum) params.set("runtime_max", runtimeMaximum);
  params.set("country", countryInput.value);
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
  const runtimeLabel = runtimeInput.options[runtimeInput.selectedIndex].text;
  label = `${label} · ${genreLabel} · ${runtimeLabel} · ${popularityLabel}`;
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
  report.recommendations.forEach((movie) => list.append(renderMovie(movie)));
  if (!report.recommendations.length) {
    list.innerHTML = `<div class="empty">No recommendations match this year range. Try widening it.</div>`;
  }
  if (report.unavailable_candidate_details) {
    notice.hidden = false;
    notice.textContent = `${report.unavailable_candidate_details} stale or unavailable catalog records were skipped safely.`;
  }
  lowestList.innerHTML = "";
  (report.lowest_recommendations || []).forEach((movie, index) => {
    lowestList.append(renderMovie(movie, `LOW ${index + 1}`));
  });
  if (!(report.lowest_recommendations || []).length) {
    lowestList.innerHTML = `<div class="empty">Lowest-score results will appear after the ranking is updated.</div>`;
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
  profileAccuracy.hidden = true;
  profileAccuracy.innerHTML = "";
  selectedManualMovie = null;
  manualMovieResults.hidden = true;
  manualMovieResults.innerHTML = "";
  manualRatingFields.hidden = true;
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
  const groupActive = view === "group";
  document.querySelector("#personal-view").hidden = groupActive;
  document.querySelector("#group-view").hidden = !groupActive;
  viewTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  history.replaceState(null, "", groupActive ? "#movie-night" : location.pathname);
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
  showProfileStatsButton.disabled = true;
  showProfileStatsButton.textContent = "Loading…";
  try {
    const response = await fetch(`/profiles/${encodeURIComponent(user)}/stats`);
    const stats = await responseJson(response);
    if (!response.ok) throw new Error(stats.detail || "Profile statistics could not be loaded");
    const value = (label, number) => `
      <div class="profile-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(number ?? "—")}</strong></div>`;
    const distribution = Object.entries(stats.rating_distribution)
      .filter(([, count]) => count)
      .map(([rating, count]) => `<span>${rating} ★ · <b>${count}</b></span>`)
      .join("");
    profileStats.innerHTML = [
      value("Rated films", stats.rated_films),
      value("Average rating", stats.average_rating?.toFixed(2)),
      value("Median rating", stats.median_rating?.toFixed(2)),
      value("Rating range", stats.lowest_rating == null ? null : `${stats.lowest_rating}–${stats.highest_rating}`),
      value("Rated reviews", stats.rated_reviews),
      value("Rewatches", stats.rewatches),
      value("Mapped", stats.mapped_films),
      value("Needs mapping", stats.pending_films),
      stats.rewatched_titles?.length
        ? `<div class="rewatch-audit"><span><b>Rewatches counted from Letterboxd diary</b></span>${stats.rewatched_titles.map((item) => `<span>${escapeHtml(item.title)} · <b>${item.count}</b></span>`).join("")}</div>`
        : `<div class="rewatch-audit"><span>No diary entries were marked as rewatches.</span></div>`,
      `<div class="rating-distribution"><span><b>Rating distribution</b></span>${distribution || "No ratings"}</div>`,
    ].join("");
    profileStats.hidden = false;
  } catch (error) {
    profileEditorStatus.textContent = error.message;
  } finally {
    showProfileStatsButton.disabled = false;
    showProfileStatsButton.textContent = "View stats";
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
    profileAccuracy.innerHTML = `
      <div class="accuracy-intro"><strong>How well does this profile predict ratings it has not trained on?</strong><span>${escapeHtml(result.method)} · ${result.linked_ratings} evaluation-ready ratings · ${escapeHtml(result.reliability)} evidence</span></div>
      <p class="weight-summary"><b>Automatically selected catalog blend:</b> ${escapeHtml(weightSummary)}<br /><b>New and unlinked titles:</b> ${escapeHtml(coldWeightSummary)}</p>
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
  selectedManualMovieLabel.textContent = `${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
  manualRatingFields.hidden = false;
  manualRatingStatus.textContent = "Movie selected. Choose a rating and optionally add a review.";
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
    const params = new URLSearchParams({ q: query });
    if (manualMovieYearInput.value) params.set("year", manualMovieYearInput.value);
    const response = await fetch(`/movies/rating-search?${params}`);
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Movie search failed");
    result.results.forEach((movie) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "manual-movie-option";
      option.innerHTML = `${movie.poster_url ? `<img src="${escapeHtml(movie.poster_url)}" alt="" loading="lazy" />` : '<span class="manual-movie-poster-placeholder"></span>'}<span><b>${escapeHtml(movie.title)}</b><small>${escapeHtml(movie.year ?? "Year unavailable")}</small></span>`;
      option.addEventListener("click", () => chooseManualMovie(movie));
      manualMovieResults.append(option);
    });
    manualMovieResults.hidden = !result.results.length;
    manualRatingStatus.textContent = result.results.length
      ? "Choose the correct title below."
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
      ? `${savedTitle} was saved at ${savedRating.toFixed(1)} stars. Recommendations and personalized weights were updated.`
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
    const params = new URLSearchParams({ q: query, limit: "10", country: countryInput.value });
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
    limit: Number(groupLimitInput.value),
    popularity: groupPopularityInput.value,
    genre: groupGenreInput.value || null,
    include_watched: groupIncludeWatchedInput.checked,
    year_min: groupYearMinInput.value ? Number(groupYearMinInput.value) : null,
    year_max: groupYearMaxInput.value ? Number(groupYearMaxInput.value) : null,
    runtime_min: runtimeMinimum,
    runtime_max: runtimeMaximum,
    country: groupCountryInput.value,
  };
  try {
    const response = await fetch("/groups/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await responseJson(response);
    if (!response.ok) throw new Error(result.detail || "Group ranking failed");
    groupStatus.textContent =
      `${result.eligible_for_everyone.toLocaleString()} shared candidates were eligible for everyone. ` +
      `Ranked in ${((performance.now() - startedAt) / 1000).toFixed(1)} seconds. ` +
      "The group score rewards a strong average while protecting the least enthusiastic person." +
      (result.include_watched ? " Rewatches are included with a proportional penalty." : " Showing new-to-everyone movies only.");
    result.recommendations.forEach((movie) => groupResults.append(renderMovie(movie)));
    if (!result.recommendations.length) {
      groupResults.innerHTML = `<div class="empty">No shared unwatched movies matched these filters.</div>`;
    }
    (result.lowest_recommendations || []).forEach((movie, index) => {
      groupLowestResults.append(renderMovie(movie, `LOW ${index + 1}`));
    });
    groupLowestHeading.hidden = !(result.lowest_recommendations || []).length;
    (result.most_divisive || []).forEach((movie, index) => {
      const personSection = document.createElement("section");
      personSection.className = "person-split";
      const personName = movie.featured_enthusiast_display_name || `Person ${index + 1}`;
      personSection.innerHTML = `<div class="person-split-heading"><strong>${escapeHtml(personName)}'s split</strong><span>${escapeHtml(movie.featured_enthusiasm_label || "best available contrast")}</span></div>`;
      personSection.append(renderMovie(movie, "SPLIT"));
      groupDivisiveResults.append(personSection);
    });
    groupDivisiveHeading.hidden = !(result.most_divisive || []).length;
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
        country: groupCountryInput.value,
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
showProfileAccuracyButton.addEventListener("click", showProfileAccuracy);
exportProfileButton.addEventListener("click", exportProfile);
findManualMovieButton.addEventListener("click", findManualMovie);
saveManualRatingButton.addEventListener("click", saveManualRating);
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
Promise.all([loadCatalogStatus(), loadProfiles(preferredProfile)])
  .then(() => loadRecommendations())
  .catch((error) => {
    list.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  });
switchView(location.hash === "#movie-night" ? "group" : "personal");
