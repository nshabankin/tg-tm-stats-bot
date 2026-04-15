const tg = window.Telegram?.WebApp;

const FAVORITES_STORAGE_KEY = "gfs.favoriteLeagues";
const VALID_VIEWS = new Set(["table", "teams"]);

const state = {
  leagues: [],
  selectedLeague: null,
  snapshot: null,
  view: "table",
  selectedTeamSlug: null,
  teamQuery: "",
  playerSort: "shirt",
  favoriteLeagues: [],
};

const leaguePickerEl = document.getElementById("league-picker");
const leagueContentEl = document.getElementById("league-content");
const snapshotMetaEl = document.getElementById("snapshot-meta");
const leagueSummaryEl = document.getElementById("league-summary");
const tableViewEl = document.getElementById("table-view");
const teamsViewEl = document.getElementById("teams-view");
const dialogEl = document.getElementById("player-dialog");
const dialogBodyEl = document.getElementById("player-dialog-body");

function renderTeamLogo(team, className) {
  if (!team.logo) {
    return "";
  }
  return `<img class="${className}" src="${team.logo}" alt="${team.club} logo" loading="lazy" />`;
}

function parseRoute() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  return {
    league: params.get("league"),
    team: params.get("team"),
    view: VALID_VIEWS.has(view) ? view : "table",
  };
}

function updateRoute() {
  const params = new URLSearchParams(window.location.search);
  if (state.selectedLeague) {
    params.set("league", state.selectedLeague);
  } else {
    params.delete("league");
  }
  if (state.view && state.view !== "table") {
    params.set("view", state.view);
  } else {
    params.delete("view");
  }
  if (state.view === "teams" && state.selectedTeamSlug) {
    params.set("team", state.selectedTeamSlug);
  } else {
    params.delete("team");
  }
  const nextUrl = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, "", nextUrl.endsWith("?") ? window.location.pathname : nextUrl);
}

function apiFetch(path) {
  return fetch(path, {
    headers: {
      Accept: "application/json",
    },
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  });
}

function normalizeSearch(value) {
  return `${value || ""}`.trim().toLowerCase();
}

function parseStatNumber(value) {
  const normalized = `${value || ""}`.trim();
  if (!normalized || normalized === "-") {
    return 0;
  }
  const digits = normalized.replace(/[^0-9]/g, "");
  return digits ? parseInt(digits, 10) : 0;
}

function loadFavoriteLeagues() {
  try {
    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
  } catch (_error) {
    return [];
  }
}

function saveFavoriteLeagues() {
  window.localStorage.setItem(
    FAVORITES_STORAGE_KEY,
    JSON.stringify(state.favoriteLeagues)
  );
}

function isFavoriteLeague(leagueKey) {
  return state.favoriteLeagues.includes(leagueKey);
}

function toggleFavoriteLeague(leagueKey) {
  if (isFavoriteLeague(leagueKey)) {
    state.favoriteLeagues = state.favoriteLeagues.filter((key) => key !== leagueKey);
  } else {
    state.favoriteLeagues = [leagueKey, ...state.favoriteLeagues];
  }
  saveFavoriteLeagues();
  renderLeaguePicker();
}

function sortedLeagues() {
  return [...state.leagues].sort((left, right) => {
    const leftFavorite = isFavoriteLeague(left.key) ? 0 : 1;
    const rightFavorite = isFavoriteLeague(right.key) ? 0 : 1;
    if (leftFavorite !== rightFavorite) {
      return leftFavorite - rightFavorite;
    }
    return left.label.localeCompare(right.label);
  });
}

function renderLeaguePicker() {
  leaguePickerEl.innerHTML = sortedLeagues()
    .map(
      (league) => `
        <article class="league-chip-card ${league.key === state.selectedLeague ? "is-active" : ""}">
          <button type="button" class="league-chip" data-league-key="${league.key}">
            ${league.logoUrl ? `<img class="league-chip-logo" src="${league.logoUrl}" alt="${league.label} logo" loading="lazy" />` : ""}
            <span class="league-chip-label">${league.buttonLabel}</span>
          </button>
          <button
            type="button"
            class="favorite-chip ${isFavoriteLeague(league.key) ? "is-active" : ""}"
            data-favorite-key="${league.key}"
            aria-label="${isFavoriteLeague(league.key) ? "Remove favorite" : "Add favorite"}"
            title="${isFavoriteLeague(league.key) ? "Remove favorite" : "Add favorite"}"
          >
            ★
          </button>
        </article>
      `
    )
    .join("");

  leaguePickerEl.querySelectorAll("[data-league-key]").forEach((button) => {
    button.addEventListener("click", () => {
      selectLeague(button.dataset.leagueKey);
    });
  });

  leaguePickerEl.querySelectorAll("[data-favorite-key]").forEach((button) => {
    button.addEventListener("click", () => {
      toggleFavoriteLeague(button.dataset.favoriteKey);
    });
  });
}

function formatDateLabel(value) {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function renderSnapshotMeta() {
  if (!state.snapshot) {
    snapshotMetaEl.innerHTML = "";
    return;
  }

  const meta = state.snapshot.meta || {};
  snapshotMetaEl.innerHTML = `
    <article class="snapshot-meta-card">
      <div>
        <p class="summary-label">Season</p>
        <p class="snapshot-meta-value">${meta.seasonLabel || "-"}</p>
      </div>
      <div>
        <p class="summary-label">Snapshot</p>
        <p class="snapshot-meta-copy">${meta.source || "Local snapshot"}</p>
      </div>
      <div>
        <p class="summary-label">Updated</p>
        <p class="snapshot-meta-copy">${formatDateLabel(meta.updatedAt)}</p>
      </div>
    </article>
  `;
}

function summaryCard(label, value, caption = "") {
  return `
    <article class="summary-card">
      <p class="summary-label">${label}</p>
      <p class="summary-value">${value || "-"}</p>
      ${caption ? `<p class="summary-caption">${caption}</p>` : ""}
    </article>
  `;
}

function renderSummary() {
  if (!state.snapshot) {
    leagueSummaryEl.innerHTML = "";
    return;
  }

  const league = state.snapshot.league || {};
  const highlights = state.snapshot.highlights || {};
  leagueSummaryEl.innerHTML = [
    summaryCard("League", league.label, `${highlights.clubs || 0} clubs`),
    summaryCard(
      "Leader",
      highlights.leader?.club,
      highlights.leader?.points ? `${highlights.leader.points} pts` : ""
    ),
    summaryCard(
      "Top Scorer",
      highlights.topScorer?.name,
      highlights.topScorer?.value
        ? `${highlights.topScorer.value} goals · ${highlights.topScorer.club}`
        : ""
    ),
    summaryCard(
      "Top Assister",
      highlights.topAssister?.name,
      highlights.topAssister?.value
        ? `${highlights.topAssister.value} assists · ${highlights.topAssister.club}`
        : ""
    ),
    summaryCard(
      "Most Goals",
      highlights.topScoringClub?.club,
      highlights.topScoringClub?.goals
        ? `${highlights.topScoringClub.goals} scored`
        : ""
    ),
    summaryCard(
      "Most Used",
      highlights.ironMan?.name,
      highlights.ironMan?.value
        ? `${highlights.ironMan.value} minutes · ${highlights.ironMan.club}`
        : `${highlights.players || 0} players`
    ),
  ].join("");
}

function renderFormPills(form) {
  const tokens = (form || "").split("").filter(Boolean);
  if (!tokens.length) {
    return '<span class="form-pill">-</span>';
  }

  return tokens
    .map((token) => {
      const kind =
        token === "W" ? "win" : token === "D" ? "draw" : token === "L" ? "loss" : "";
      return `<span class="form-pill ${kind}">${token}</span>`;
    })
    .join("");
}

function openTeamFromTable(teamSlug) {
  state.view = "teams";
  state.selectedTeamSlug = teamSlug;
  renderView();
  updateRoute();
  teamsViewEl.querySelector(`[data-team-card="${teamSlug}"]`)?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

function renderTable() {
  tableViewEl.innerHTML = `
    <div class="table-shell">
      <div class="table-scroll">
        <div class="table-head">
          <span>#</span>
          <span>Club</span>
          <span>P</span>
          <span>Pts</span>
          <span>W-D-L</span>
          <span>GD</span>
          <span>Form</span>
        </div>
        ${state.snapshot.table
          .map(
            (row) => `
              <button type="button" class="table-row table-row-button" data-table-team="${row.slug}">
                <span class="table-rank">${row.rank}</span>
                <div class="table-club-wrap">
                  ${renderTeamLogo(row, "table-logo")}
                  <span class="table-club-name">${row.club}</span>
                </div>
                <span class="table-stat">${row.played}</span>
                <span class="table-points">${row.points}</span>
                <span class="table-stat">${row.wins}-${row.draws}-${row.losses}</span>
                <span class="table-stat">${row.diff}</span>
                <div class="table-form-row">
                  ${renderFormPills(row.form || "")}
                </div>
              </button>
            `
          )
          .join("")}
      </div>
    </div>
  `;

  tableViewEl.querySelectorAll("[data-table-team]").forEach((button) => {
    button.addEventListener("click", () => {
      openTeamFromTable(button.dataset.tableTeam);
    });
  });
}

function filteredTeams() {
  const query = normalizeSearch(state.teamQuery);
  if (!query) {
    return state.snapshot.teams;
  }

  return state.snapshot.teams.filter((team) => {
    if (normalizeSearch(team.club).includes(query)) {
      return true;
    }
    return team.players.some((player) => normalizeSearch(player.name).includes(query));
  });
}

function sortedPlayers(players) {
  const items = [...players];
  const sorters = {
    shirt: (left, right) => {
      const leftNumber = left.shirtNumber ? parseStatNumber(left.shirtNumber) : 999;
      const rightNumber = right.shirtNumber ? parseStatNumber(right.shirtNumber) : 999;
      if (leftNumber !== rightNumber) {
        return leftNumber - rightNumber;
      }
      return left.name.localeCompare(right.name);
    },
    goals: (left, right) =>
      parseStatNumber(right.stats?.goals) - parseStatNumber(left.stats?.goals) ||
      left.name.localeCompare(right.name),
    assists: (left, right) =>
      parseStatNumber(right.stats?.assists) - parseStatNumber(left.stats?.assists) ||
      left.name.localeCompare(right.name),
    minutes: (left, right) =>
      parseStatNumber(right.stats?.minutes) - parseStatNumber(left.stats?.minutes) ||
      left.name.localeCompare(right.name),
  };
  return items.sort(sorters[state.playerSort] || sorters.shirt);
}

function renderTeamControls(count) {
  return `
    <div class="team-controls">
      <label class="field-shell">
        <span class="field-label">Search clubs or players</span>
        <input
          type="search"
          class="text-input"
          placeholder="Arsenal, Saka, Zenit..."
          value="${state.teamQuery}"
          id="team-search"
        />
      </label>
      <label class="field-shell">
        <span class="field-label">Player sort</span>
        <select class="select-input" id="player-sort">
          <option value="shirt" ${state.playerSort === "shirt" ? "selected" : ""}>Shirt number</option>
          <option value="goals" ${state.playerSort === "goals" ? "selected" : ""}>Goals</option>
          <option value="assists" ${state.playerSort === "assists" ? "selected" : ""}>Assists</option>
          <option value="minutes" ${state.playerSort === "minutes" ? "selected" : ""}>Minutes</option>
        </select>
      </label>
      <div class="team-results-copy">
        <p class="summary-label">Showing</p>
        <p class="team-results-value">${count} clubs</p>
      </div>
    </div>
  `;
}

function renderTeams() {
  const teams = filteredTeams();
  const selected =
    teams.find((team) => team.slug === state.selectedTeamSlug) || null;
  state.selectedTeamSlug = selected ? selected.slug : null;

  const teamCards = teams
    .map((team) => {
      const players = sortedPlayers(team.players);
      return `
        <article class="team-card ${team.slug === state.selectedTeamSlug ? "is-active" : ""}" data-team-card="${team.slug}">
          <button
            type="button"
            class="team-card-toggle"
            data-team-slug="${team.slug}"
          >
            <div class="team-card-header">
              <span class="rank-badge team-rank-badge">${team.rank}</span>
              ${renderTeamLogo(team, "team-logo")}
              <div class="team-card-copy">
                <h3 class="club-name">${team.club}</h3>
                <p class="team-card-subtitle">${team.points} pts · GD ${team.diff} · ${team.playerCount} players</p>
              </div>
              <span class="team-toggle-indicator">${team.slug === state.selectedTeamSlug ? "−" : "+"}</span>
            </div>
          </button>
          ${
            team.slug === state.selectedTeamSlug
              ? `
                <div class="team-card-body">
                  <div class="team-insight-row">
                    <span class="team-insight-pill">Record ${team.wins}-${team.draws}-${team.losses}</span>
                    <span class="team-insight-pill">Goals ${team.goals}</span>
                    <span class="team-insight-pill">Form ${team.form || "-"}</span>
                  </div>
                  <div class="player-list">
                    ${players
                      .map(
                        (player) => `
                          <button
                            type="button"
                            class="player-button"
                            data-team-slug="${team.slug}"
                            data-player-id="${player.id}"
                          >
                            <p class="player-name">${
                              player.shirtNumber ? `#${player.shirtNumber} ` : ""
                            }${player.name}</p>
                            <p class="player-position">${player.position || "Unknown role"}</p>
                            <p class="player-meta">${player.stats?.goals || "-"} goals · ${player.stats?.assists || "-"} assists · ${player.stats?.minutes || "-"} mins</p>
                          </button>
                        `
                      )
                      .join("")}
                  </div>
                </div>
              `
              : ""
          }
        </article>
      `;
    })
    .join("");

  teamsViewEl.innerHTML = `
    <div class="team-list-shell">
      <div class="team-list-header">
        <p class="team-card-subtitle">Open a club for its squad, or search straight for a player.</p>
      </div>
      ${renderTeamControls(teams.length)}
      ${
        teams.length
      ? `<div class="team-list">${teamCards}</div>`
          : '<div class="empty-state">No clubs or players match that search yet.</div>'
      }
    </div>
  `;

  const searchInput = teamsViewEl.querySelector("#team-search");
  const sortSelect = teamsViewEl.querySelector("#player-sort");
  if (searchInput) {
    searchInput.addEventListener("input", (event) => {
      state.teamQuery = event.target.value;
      renderTeams();
      const nextInput = teamsViewEl.querySelector("#team-search");
      nextInput?.focus();
      nextInput?.setSelectionRange(nextInput.value.length, nextInput.value.length);
    });
  }
  if (sortSelect) {
    sortSelect.addEventListener("change", (event) => {
      state.playerSort = event.target.value;
      renderTeams();
    });
  }

  teamsViewEl.querySelectorAll("[data-team-slug]").forEach((button) => {
    button.addEventListener("click", () => {
      const { teamSlug, playerId } = button.dataset;
      if (playerId) {
        openPlayer(teamSlug, playerId);
        return;
      }
      state.selectedTeamSlug =
        state.selectedTeamSlug === teamSlug ? null : teamSlug;
      renderTeams();
      updateRoute();
      if (state.selectedTeamSlug) {
        teamsViewEl.querySelector(`[data-team-card="${teamSlug}"]`)?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    });
  });
}

function renderView() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.view === state.view);
  });

  tableViewEl.classList.toggle("hidden", state.view !== "table");
  teamsViewEl.classList.toggle("hidden", state.view !== "teams");

  if (state.view === "table") {
    renderTable();
  } else {
    renderTeams();
  }
}

function buildStatCard(label, value) {
  const normalized = `${value || ""}`.trim();
  if (!normalized || normalized === "-") {
    return "";
  }
  return `
    <article class="stat-card">
      <p class="stat-card-label">${label}</p>
      <p class="stat-card-value">${normalized}</p>
    </article>
  `;
}

function openPlayer(teamSlug, playerId) {
  const team = state.snapshot.teams.find((item) => item.slug === teamSlug);
  const player = team?.players.find((item) => item.id === playerId);
  if (!team || !player) {
    return;
  }

  const stats = player.stats || {};
  const goalShare =
    parseStatNumber(stats.goals) && team.goalsFor
      ? `${Math.round((parseStatNumber(stats.goals) / team.goalsFor) * 100)}%`
      : "";

  dialogBodyEl.innerHTML = `
    <div class="player-dialog-panel">
      <p class="eyebrow">${team.club}</p>
      <h2 class="club-name">${player.name}</h2>
      <p class="subtitle">
        ${player.position || "Unknown role"}${
          player.shirtNumber ? ` · #${player.shirtNumber}` : ""
        }
      </p>
      <div class="player-context-row">
        <span class="team-insight-pill">Rank #${team.rank}</span>
        <span class="team-insight-pill">${team.points} pts</span>
        <span class="team-insight-pill">Form ${team.form || "-"}</span>
      </div>
      <div class="stats-grid">
        ${[
          buildStatCard("Played", stats.played),
          buildStatCard("Goals", stats.goals),
          buildStatCard("Assists", stats.assists),
          buildStatCard("Minutes", stats.minutes),
          buildStatCard("Goal Share", goalShare),
          buildStatCard("Yellow", stats.yellowCards),
          buildStatCard("Red", stats.redCards),
          buildStatCard("Clean Sheets", stats.cleanSheets),
          buildStatCard("Conceded", stats.conceded),
        ].join("")}
      </div>
      <div class="dialog-actions">
        <form method="dialog">
          <button type="submit" class="secondary-button">Close</button>
        </form>
      </div>
    </div>
  `;
  dialogEl.showModal();
}

async function selectLeague(leagueKey, options = {}) {
  state.selectedLeague = leagueKey;
  state.teamQuery = "";
  renderLeaguePicker();

  const snapshot = await apiFetch(`/api/leagues/${leagueKey}/snapshot`);
  state.snapshot = snapshot;
  state.selectedTeamSlug = options.teamSlug || null;
  leagueContentEl.classList.remove("hidden");
  renderSnapshotMeta();
  renderSummary();
  renderView();
  updateRoute();
}

function setView(nextView) {
  state.view = VALID_VIEWS.has(nextView) ? nextView : "table";
  renderView();
  updateRoute();
}

async function boot() {
  tg?.ready();
  tg?.expand();

  state.favoriteLeagues = loadFavoriteLeagues();

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      setView(tab.dataset.view);
    });
  });

  const leagueResponse = await apiFetch("/api/leagues");
  state.leagues = leagueResponse.leagues;
  renderLeaguePicker();

  const route = parseRoute();
  const favoriteFirst = state.favoriteLeagues.find((key) =>
    state.leagues.some((league) => league.key === key)
  );
  const initialLeague =
    route.league || favoriteFirst || state.leagues[0]?.key;

  state.view = route.view;
  if (initialLeague) {
    await selectLeague(initialLeague, { teamSlug: route.team });
  }
}

boot().catch((error) => {
  leagueContentEl.classList.remove("hidden");
  snapshotMetaEl.innerHTML = "";
  leagueSummaryEl.innerHTML = "";
  tableViewEl.innerHTML = `<div class="empty-state">Could not load snapshot data: ${error.message}</div>`;
});
