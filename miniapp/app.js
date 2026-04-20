const tg = window.Telegram?.WebApp;

const FAVORITES_STORAGE_KEY = "gfs.favoriteLeagues";
const VALID_VIEWS = new Set(["table", "teams", "matches", "bracket"]);

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
const matchesViewEl = document.getElementById("matches-view");
const bracketViewEl = document.getElementById("bracket-view");
const dialogEl = document.getElementById("player-dialog");
const dialogBodyEl = document.getElementById("player-dialog-body");

function renderTeamLogo(team, className) {
  if (!team.logo) {
    return "";
  }
  return `<img class="${className}" src="${team.logo}" alt="${team.club} logo" loading="lazy" />`;
}

function leagueFamily() {
  return state.snapshot?.league?.family || "domestic";
}

function hasBracket() {
  return Boolean(state.snapshot?.bracket?.rounds?.length);
}

function hasMatches() {
  return Boolean(state.snapshot?.matches?.groups?.length);
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

function normalizeClubKey(value) {
  return `${value || ""}`
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
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
    state.favoriteLeagues = [...state.favoriteLeagues, leagueKey];
  }
  saveFavoriteLeagues();
  renderLeaguePicker();
}

function sortedLeagues() {
  const leaguesByKey = new Map(state.leagues.map((league) => [league.key, league]));
  const favorites = state.favoriteLeagues
    .map((key) => leaguesByKey.get(key))
    .filter(Boolean);
  const remaining = state.leagues.filter((league) => !isFavoriteLeague(league.key));
  return [...favorites, ...remaining];
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

function applyLeagueTheme() {
  if (!state.selectedLeague) {
    return;
  }
  const chip = document.querySelector(
    `.league-chip[data-league-key="${state.selectedLeague}"]`
  );
  if (!chip) {
    return;
  }
  const computed = getComputedStyle(chip);
  const accent = `${computed.getPropertyValue("--league-accent") || ""}`.trim();
  if (accent) {
    document.documentElement.style.setProperty("--page-accent", accent);
  }
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

function compactName(fullName) {
  const name = `${fullName || ""}`.trim();
  if (!name) {
    return "";
  }
  const parts = name.split(/\s+/);
  if (parts.length === 1) {
    return parts[0];
  }
  return parts[parts.length - 1];
}

function compactClubName(fullName) {
  const name = `${fullName || ""}`.trim();
  if (!name) {
    return "";
  }

  const parts = name
    .split(/\s+/)
    .filter((part) => !["fc", "cf", "afc", "sc"].includes(part.toLowerCase()));

  if (!parts.length) {
    return name;
  }

  if (parts.length === 1) {
    return parts[0];
  }

  if (parts[0].length <= 3) {
    return parts.slice(0, 2).join(" ");
  }

  return parts[0];
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
        ? `${highlights.topScorer.value} goals · ${compactName(highlights.topScorer.club)}`
        : ""
    ),
    summaryCard(
      "Top Assister",
      highlights.topAssister?.name,
      highlights.topAssister?.value
        ? `${highlights.topAssister.value} assists · ${compactName(highlights.topAssister.club)}`
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
        ? `${highlights.ironMan.value} minutes · ${compactName(highlights.ironMan.club)}`
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

function tableColumns() {
  if (leagueFamily() === "uefa") {
    return [
      { key: "rank", label: "#" , className: "table-rank"},
      { key: "club", label: "Club", className: "table-club"},
      { key: "played", label: "P", className: "table-stat" },
      { key: "points", label: "Pts", className: "table-points" },
      { key: "goals", label: "Goals", className: "table-stat" },
      { key: "diff", label: "GD", className: "table-stat" },
    ];
  }

  return [
    { key: "rank", label: "#", className: "table-rank" },
    { key: "club", label: "Club", className: "table-club" },
    { key: "played", label: "P", className: "table-stat" },
    { key: "points", label: "Pts", className: "table-points" },
    { key: "wdl", label: "W-D-L", className: "table-stat" },
    { key: "diff", label: "GD", className: "table-stat" },
    { key: "form", label: "Form", className: "table-form" },
  ];
}

function tableColumnTemplate() {
  return leagueFamily() === "uefa"
    ? "40px minmax(180px, 1fr) 34px 48px 68px 40px"
    : "40px minmax(180px, 1fr) 34px 48px 76px 40px 128px";
}

function renderTableCell(row, column) {
  if (column.key === "rank") {
    return `<span class="table-rank">${row.rank}</span>`;
  }
  if (column.key === "club") {
    return `
      <div class="table-club-wrap">
        ${renderTeamLogo(row, "table-logo")}
        <span class="table-club-name">${row.club}</span>
      </div>
    `;
  }
  if (column.key === "points") {
    return `<span class="table-points">${row.points}</span>`;
  }
  if (column.key === "wdl") {
    return `<span class="table-stat">${row.wins}-${row.draws}-${row.losses}</span>`;
  }
  if (column.key === "form") {
    return `<div class="table-form-row">${renderFormPills(row.form || "")}</div>`;
  }
  return `<span class="table-stat">${row[column.key] ?? "-"}</span>`;
}

function renderTable() {
  const columns = tableColumns();
  const columnTemplate = tableColumnTemplate();
  tableViewEl.innerHTML = `
    <div class="table-shell ${leagueFamily() === "uefa" ? "is-uefa" : ""}">
      <div class="table-scroll" style="--table-columns: ${columnTemplate}">
        <div class="table-head">
          ${columns.map((column) => `<span>${column.label}</span>`).join("")}
        </div>
        ${state.snapshot.table
          .map(
            (row) => `
              <button type="button" class="table-row table-row-button" data-table-team="${row.slug}">
                ${columns.map((column) => renderTableCell(row, column)).join("")}
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

function statText(value, label) {
  const normalized = `${value || ""}`.trim();
  if (!normalized || normalized === "-") {
    return "";
  }
  return `${normalized} ${label}`;
}

function playerPreviewStats(player) {
  const stats = player.stats || {};
  const isGoalkeeper =
    `${player.position || ""}`.toLowerCase().includes("goalkeeper") ||
    Boolean(`${stats.cleanSheets || ""}`.trim()) ||
    Boolean(`${stats.conceded || ""}`.trim());

  const items = isGoalkeeper
    ? [
        statText(stats.cleanSheets, "clean sheets"),
        statText(stats.conceded, "conceded"),
        statText(stats.minutes, "mins"),
      ]
    : [
        statText(stats.goals, "goals"),
        statText(stats.assists, "assists"),
        statText(stats.minutes, "mins"),
      ];

  return items.filter(Boolean);
}

function playerModalStats(player) {
  const stats = player.stats || {};
  const isGoalkeeper = `${player.position || ""}`
    .toLowerCase()
    .includes("goalkeeper");

  const items = [
    ["Played", stats.played],
    ["Minutes", stats.minutes],
  ];

  if (isGoalkeeper) {
    items.push(["Clean Sheets", stats.cleanSheets]);
    items.push(["Conceded", stats.conceded]);
    items.push(["Yellow", stats.yellowCards]);
    items.push(["Red", stats.redCards]);
  } else {
    items.push(["Goals", stats.goals]);
    items.push(["Assists", stats.assists]);
    items.push(["Yellow", stats.yellowCards]);
    items.push(["Red", stats.redCards]);
  }

  return items.filter(([, value]) => {
    const normalized = `${value || ""}`.trim();
    return normalized && normalized !== "-";
  });
}

function teamSearchPlaceholder() {
  if (!state.snapshot) {
    return "Search clubs or players...";
  }
  const teamHint = compactClubName(state.snapshot.table?.[0]?.club || "");
  const scorerHint = compactName(state.snapshot.highlights?.topScorer?.name || "");
  const assisterHint = compactName(state.snapshot.highlights?.topAssister?.name || "");
  return [teamHint, scorerHint, assisterHint]
    .filter(Boolean)
    .join(", ");
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
          placeholder="${teamSearchPlaceholder() || "Search clubs or players..."}"
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
                    ${
                      team.wins || team.draws || team.losses
                        ? `<span class="team-insight-pill">Record ${team.wins}-${team.draws}-${team.losses}</span>`
                        : `<span class="team-insight-pill">Played ${team.played}</span>`
                    }
                    <span class="team-insight-pill">Pts ${team.points}</span>
                    <span class="team-insight-pill">Goals ${team.goals}</span>
                    <span class="team-insight-pill">GD ${team.diff}</span>
                    ${
                      team.form
                        ? `<span class="team-insight-pill">Form ${team.form}</span>`
                        : ""
                    }
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
                            ${
                              playerPreviewStats(player).length
                                ? `<p class="player-meta">${playerPreviewStats(player).join(" · ")}</p>`
                                : '<p class="player-meta">No detailed stats in current snapshot</p>'
                            }
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

function bracketTeamMarkup(teamName, logoByClub) {
  const logo = logoByClub.get(teamName);
  return `
    <div class="bracket-team">
      ${logo ? `<img class="bracket-team-logo" src="${logo}" alt="${teamName} logo" loading="lazy" />` : ""}
      <span class="bracket-team-name">${teamName}</span>
    </div>
  `;
}

function bracketRoundSizeLabel(round) {
  const count = round.ties?.length || 0;
  return `${count} ${count === 1 ? "tie" : "ties"}`;
}

function parseScore(value) {
  const text = `${value || ""}`;
  const main = text.match(/(\d+)\s*:\s*(\d+)/);
  if (!main) {
    return null;
  }
  const after = text.slice(main.index + main[0].length);
  const pen = after.match(/\((\d+)\s*:\s*(\d+)\)/);
  return {
    home: Number(main[1]),
    away: Number(main[2]),
    penHome: pen ? Number(pen[1]) : null,
    penAway: pen ? Number(pen[2]) : null,
  };
}

function aggregateTie(tie) {
  const matches = Array.isArray(tie?.matches) ? tie.matches : [];
  const first = matches[0] || {};
  const teamA = first.homeTeam || "";
  const teamB = first.awayTeam || "";

  const totals = new Map([
    [teamA, 0],
    [teamB, 0],
  ]);
  let hasScore = false;

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const parseMatchDate = (value) => {
    const text = `${value || ""}`;
    const match = text.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (!match) {
      return null;
    }
    const day = parseInt(match[1], 10);
    const month = parseInt(match[2], 10);
    const year = parseInt(match[3], 10);
    const date = new Date(year, month - 1, day);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  matches.forEach((match) => {
    const score = parseScore(match.result);
    if (!score) {
      return;
    }
    // Transfermarkt can show "0:0" placeholders before kick-off. Hide those until
    // the match date has passed to avoid confusing empty fixtures as results.
    if (score.home === 0 && score.away === 0) {
      const when = parseMatchDate(match.date);
      if (when && when.getTime() >= today.getTime()) {
        return;
      }
    }
    hasScore = true;
    const home = match.homeTeam || "";
    const away = match.awayTeam || "";
    if (!totals.has(home)) {
      totals.set(home, 0);
    }
    if (!totals.has(away)) {
      totals.set(away, 0);
    }
    totals.set(home, (totals.get(home) || 0) + score.home);
    totals.set(away, (totals.get(away) || 0) + score.away);
  });

  const goalsA = totals.get(teamA) ?? 0;
  const goalsB = totals.get(teamB) ?? 0;

  let winner = "";
  if (matches.length) {
    if (goalsA > goalsB) {
      winner = teamA;
    } else if (goalsB > goalsA) {
      winner = teamB;
    } else {
      const lastScore = parseScore(matches[matches.length - 1].result);
      if (lastScore?.penHome != null && lastScore?.penAway != null) {
        // Penalties decide the winner (home/away refer to the last match teams).
        const lastHome = matches[matches.length - 1].homeTeam || "";
        const lastAway = matches[matches.length - 1].awayTeam || "";
        if (lastScore.penHome > lastScore.penAway) {
          winner = lastHome;
        } else if (lastScore.penAway > lastScore.penHome) {
          winner = lastAway;
        }
      }
    }
  }

  const display = hasScore ? `${goalsA}:${goalsB}` : "";
  const teams = new Set([teamA, teamB].filter(Boolean));
  return { teamA, teamB, goalsA, goalsB, winner, display, teams, hasScore };
}

function tieContainsTeam(tieAgg, teamName) {
  if (!teamName) {
    return false;
  }
  return tieAgg.teams.has(teamName);
}

function drawBracketLines(viewportEl) {
  const scrollEl = viewportEl.querySelector(".bracket-scroll");
  const svg = viewportEl.querySelector(".bracket-lines");
  if (!scrollEl || !svg) {
    return;
  }

  const rounds = Array.from(viewportEl.querySelectorAll("[data-bracket-round]"));
  if (rounds.length < 2) {
    svg.innerHTML = "";
    return;
  }

  const scrollRect = scrollEl.getBoundingClientRect();
  const width = scrollEl.scrollWidth;
  const height = Math.max(scrollEl.clientHeight, scrollEl.scrollHeight);
  svg.setAttribute("width", `${width}`);
  svg.setAttribute("height", `${height}`);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  const mkPoint = (rect) => ({
    x: rect.right - scrollRect.left + scrollEl.scrollLeft,
    y: rect.top - scrollRect.top + scrollEl.scrollTop + rect.height / 2,
  });
  const mkPointLeft = (rect) => ({
    x: rect.left - scrollRect.left + scrollEl.scrollLeft,
    y: rect.top - scrollRect.top + scrollEl.scrollTop + rect.height / 2,
  });

  const stroke = document.createElementNS("http://www.w3.org/2000/svg", "g");
  stroke.setAttribute("fill", "none");
  stroke.setAttribute("stroke", "rgba(255,255,255,0.35)");
  stroke.setAttribute("stroke-width", "2");
  stroke.setAttribute("stroke-linecap", "round");
  stroke.setAttribute("stroke-linejoin", "round");
  svg.appendChild(stroke);

  for (let roundIndex = 0; roundIndex < rounds.length - 1; roundIndex += 1) {
    const currentRound = rounds[roundIndex];
    const nextRound = rounds[roundIndex + 1];
    const currentTies = Array.from(currentRound.querySelectorAll("[data-bracket-tie]"));
    const nextTies = Array.from(nextRound.querySelectorAll("[data-bracket-tie]"));

    currentTies.forEach((tieEl, tieIndex) => {
      const winner = tieEl.getAttribute("data-bracket-winner") || "";
      let nextIndex = -1;
      if (winner) {
        nextIndex = nextTies.findIndex((nextTie) =>
          (nextTie.getAttribute("data-bracket-teams") || "")
            .split("|")
            .includes(winner)
        );
      }
      if (nextIndex < 0) {
        // Fallback to structural pairing when teams are still placeholders.
        const currentCount = currentTies.length || 1;
        const nextCount = nextTies.length || 1;
        if (nextCount === currentCount) {
          nextIndex = tieIndex;
        } else if (nextCount * 2 === currentCount) {
          nextIndex = Math.floor(tieIndex / 2);
        } else {
          nextIndex = Math.min(nextCount - 1, Math.floor((tieIndex / currentCount) * nextCount));
        }
      }
      const fromRect = tieEl.getBoundingClientRect();
      const toRect = nextTies[nextIndex].getBoundingClientRect();
      const from = mkPoint(fromRect);
      const to = mkPointLeft(toRect);
      const midX = from.x + Math.max(28, (to.x - from.x) * 0.5);

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute(
        "d",
        `M ${from.x} ${from.y} L ${midX} ${from.y} L ${midX} ${to.y} L ${to.x} ${to.y}`
      );
      stroke.appendChild(path);
    });
  }
}

function renderBracket() {
  if (!hasBracket()) {
    bracketViewEl.innerHTML = '<div class="empty-state">No knockout bracket is available in the current snapshot.</div>';
    return;
  }

  const logoByClub = new Map(
    (state.snapshot.teams || []).map((team) => [team.club, team.logo])
  );

  bracketViewEl.innerHTML = `
    <div class="bracket-viewport">
      <div class="bracket-scroll">
        <svg class="bracket-lines" aria-hidden="true"></svg>
        <div class="bracket-columns">
          ${state.snapshot.bracket.rounds
            .map(
              (round, roundIndex) => `
                <section class="bracket-round" data-bracket-round="${roundIndex}">
                  <div class="bracket-round-head">
                    <p class="bracket-round-title">${round.label}</p>
                  </div>
                  <div class="bracket-ties">
                    ${round.ties
                      .map((tie, tieIndex) => {
                        const agg = aggregateTie(tie);
                        const home = agg.teamA;
                        const away = agg.teamB;
                        const result = agg.display;
                        const winner = agg.winner;
                        const teamsAttr = [home, away].filter(Boolean).join("|");
                        return `
                          <article class="bracket-tie-card" data-bracket-tie="${tieIndex}" data-bracket-winner="${winner}" data-bracket-teams="${teamsAttr}">
                            <div class="bracket-tie-rows">
                              <div class="bracket-tie-row">
                                ${bracketTeamMarkup(home, logoByClub)}
                              </div>
                              <div class="bracket-tie-row">
                                ${bracketTeamMarkup(away, logoByClub)}
                              </div>
                            </div>
                            <div class="bracket-tie-foot">
                              <span class="bracket-tie-code">${tie.code || ""}</span>
                              <span class="bracket-result">${result || "TBD"}</span>
                            </div>
                          </article>
                        `;
                      })
                      .join("")}
                  </div>
                </section>
              `
            )
            .join("")}
        </div>
      </div>
    </div>
  `;

  // Let the layout settle, then draw connector lines.
  requestAnimationFrame(() => drawBracketLines(bracketViewEl));
}

function matchGroupLabel(group) {
  return group?.label || "Matches";
}

function matchScoreLabel(match) {
  const score = `${match?.score || ""}`.trim();
  if (!score || score === "-:-") {
    return "";
  }
  // Guardrail: the scraper occasionally picks up kickoff times (e.g. "6:45", "9:00").
  if (/^\d{1,2}:\d{2}$/.test(score)) {
    return "";
  }
  return score;
}

function renderMatches() {
  if (!hasMatches()) {
    matchesViewEl.innerHTML = '<div class="empty-state">No match snapshot is available yet. Run a refresh to generate match results.</div>';
    return;
  }

  const groups = state.snapshot.matches.groups || [];
  if (!state.matchesGroupIndex || state.matchesGroupIndex < 0) {
    state.matchesGroupIndex = 0;
  }
  state.matchesGroupIndex = Math.min(groups.length - 1, state.matchesGroupIndex);
  const group = groups[state.matchesGroupIndex];
  const matches = group?.matches || [];
  const teams = Array.isArray(state.snapshot.teams) ? state.snapshot.teams : [];
  const logoByName = new Map(teams.map((team) => [team.club, team.logo]));
  const logoByKey = new Map(
    teams.map((team) => [normalizeClubKey(team.club), team.logo])
  );

  const resolveLogo = (teamName) =>
    logoByName.get(teamName) || logoByKey.get(normalizeClubKey(teamName));

  matchesViewEl.innerHTML = `
    <div class="matches-shell">
      <div class="matches-controls">
        <button type="button" class="secondary-button" data-matches-nav="-1" ${state.matchesGroupIndex === 0 ? "disabled" : ""}>Prev</button>
        <div class="matches-title">
          <p class="summary-label">Stage</p>
          <p class="matches-title-value">${matchGroupLabel(group)}</p>
        </div>
        <button type="button" class="secondary-button" data-matches-nav="1" ${state.matchesGroupIndex === groups.length - 1 ? "disabled" : ""}>Next</button>
      </div>
      <div class="matches-list">
        ${matches
          .map((match) => {
            const score = matchScoreLabel(match);
            const homeLogo = resolveLogo(match.homeTeam);
            const awayLogo = resolveLogo(match.awayTeam);
            return `
              <article class="match-card">
                <div class="match-meta">
                  <span>${match.date || ""}${match.time ? ` · ${match.time}` : ""}</span>
                </div>
                <div class="match-row">
                  <div class="match-team match-team-home">
                    ${homeLogo ? `<img class="match-team-logo" src="${homeLogo}" alt="${match.homeTeam || "Home"} logo" loading="lazy" />` : ""}
                    <span class="match-team-name">${match.homeTeam || "-"}</span>
                  </div>
                  <div class="match-scoreline">${score || "TBD"}</div>
                  <div class="match-team match-team-away">
                    <span class="match-team-name">${match.awayTeam || "-"}</span>
                    ${awayLogo ? `<img class="match-team-logo" src="${awayLogo}" alt="${match.awayTeam || "Away"} logo" loading="lazy" />` : ""}
                  </div>
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    </div>
  `;

  matchesViewEl.querySelectorAll("[data-matches-nav]").forEach((button) => {
    button.addEventListener("click", () => {
      const delta = Number(button.dataset.matchesNav || "0");
      state.matchesGroupIndex = Math.min(groups.length - 1, Math.max(0, state.matchesGroupIndex + delta));
      renderMatches();
      updateRoute();
    });
  });
}

function renderView() {
  document.querySelectorAll(".tab").forEach((tab) => {
    if (tab.dataset.view === "bracket") {
      tab.classList.toggle("hidden", !hasBracket());
      if (!hasBracket() && state.view === "bracket") {
        state.view = "table";
      }
    }
    if (tab.dataset.view === "matches") {
      tab.classList.toggle("hidden", !hasMatches());
      if (!hasMatches() && state.view === "matches") {
        state.view = "table";
      }
    }
    tab.classList.toggle("is-active", tab.dataset.view === state.view);
  });

  tableViewEl.classList.toggle("hidden", state.view !== "table");
  teamsViewEl.classList.toggle("hidden", state.view !== "teams");
  matchesViewEl.classList.toggle("hidden", state.view !== "matches");
  bracketViewEl.classList.toggle("hidden", state.view !== "bracket");
  leagueSummaryEl.classList.toggle("hidden", state.view !== "table");

  if (state.view === "table") {
    renderTable();
  } else if (state.view === "teams") {
    renderTeams();
  } else if (state.view === "matches") {
    renderMatches();
  } else {
    renderBracket();
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

  const statCards = playerModalStats(player)
    .map(([label, value]) => buildStatCard(label, value))
    .join("");
  const hasDetailedStats = Boolean(statCards);

  dialogBodyEl.innerHTML = `
    <div class="player-dialog-panel">
      <p class="eyebrow">${team.club}</p>
      <h2 class="club-name">${player.name}</h2>
      <p class="subtitle">
        ${player.position || "Unknown role"}${
          player.shirtNumber ? ` · #${player.shirtNumber}` : ""
        }
      </p>
      ${
        hasDetailedStats
          ? `<div class="stats-grid">${statCards}</div>`
          : '<div class="empty-state modal-empty-state">No detailed stat row is available in the current snapshot for this player.</div>'
      }
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
  applyLeagueTheme();

  const snapshot = await apiFetch(`/api/leagues/${leagueKey}/snapshot`);
  state.snapshot = snapshot;
  state.matchesGroupIndex = 0;
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
