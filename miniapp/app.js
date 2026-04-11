const tg = window.Telegram?.WebApp;

const state = {
  leagues: [],
  selectedLeague: null,
  snapshot: null,
  view: "table",
  selectedTeamSlug: null,
};

const leaguePickerEl = document.getElementById("league-picker");
const leagueContentEl = document.getElementById("league-content");
const leagueSummaryEl = document.getElementById("league-summary");
const tableViewEl = document.getElementById("table-view");
const teamsViewEl = document.getElementById("teams-view");
const dialogEl = document.getElementById("player-dialog");
const dialogBodyEl = document.getElementById("player-dialog-body");

function getQueryLeague() {
  const params = new URLSearchParams(window.location.search);
  return params.get("league");
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

function renderLeaguePicker() {
  leaguePickerEl.innerHTML = "";
  state.leagues.forEach((league) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "league-chip";
    if (league.key === state.selectedLeague) {
      button.classList.add("is-active");
    }
    button.textContent = league.buttonLabel;
    button.addEventListener("click", () => selectLeague(league.key));
    leaguePickerEl.appendChild(button);
  });
}

function renderSummary() {
  const rows = state.snapshot.table;
  const leader = rows[0];
  const topScoring = [...rows].sort((left, right) => {
    const leftGoals = parseInt((left.goals || "0:0").split(":")[0], 10);
    const rightGoals = parseInt((right.goals || "0:0").split(":")[0], 10);
    return rightGoals - leftGoals;
  })[0];
  const summaryItems = [
    { label: "League", value: state.snapshot.league.label },
    { label: "Leader", value: leader ? leader.club : "-" },
    { label: "Most Goals", value: topScoring ? topScoring.club : "-" },
    { label: "Clubs", value: rows.length },
  ];

  leagueSummaryEl.innerHTML = summaryItems
    .map(
      (item) => `
        <article class="summary-card">
          <p class="summary-label">${item.label}</p>
          <p class="summary-value">${item.value}</p>
        </article>
      `
    )
    .join("");
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

function renderTable() {
  tableViewEl.innerHTML = `
    <div class="table-shell">
      <div class="table-head">
        <span>#</span>
        <span>Club</span>
        <span>P</span>
        <span>W</span>
        <span>D</span>
        <span>L</span>
        <span>GD</span>
        <span>Pts</span>
        <span>Form</span>
      </div>
      ${state.snapshot.table
        .map(
          (row) => `
          <article class="table-row">
            <span class="cell rank-cell">${row.rank}</span>
            <span class="cell club-cell">${row.club}</span>
            <span class="cell">${row.played}</span>
            <span class="cell">${row.wins}</span>
            <span class="cell">${row.draws}</span>
            <span class="cell">${row.losses}</span>
            <span class="cell">${row.diff}</span>
            <span class="cell points-cell">${row.points}</span>
            <span class="cell form-cell">${renderFormPills(row.form)}</span>
          </article>
        `
        )
        .join("")}
    </div>
  `;
}

function renderTeams() {
  const teams = state.snapshot.teams;
  const selected =
    teams.find((team) => team.slug === state.selectedTeamSlug) || teams[0] || null;
  state.selectedTeamSlug = selected ? selected.slug : null;

  const teamCards = teams
    .map(
      (team) => `
        <article class="team-card ${team.slug === state.selectedTeamSlug ? "is-active" : ""}">
          <button
            type="button"
            class="team-card-toggle"
            data-team-slug="${team.slug}"
          >
            <div class="team-card-header">
              <span class="rank-badge">${team.rank}</span>
              <div>
                <h3 class="club-name">${team.club}</h3>
                <p class="team-card-subtitle">${team.playerCount} players</p>
              </div>
              <span class="team-toggle-indicator">${team.slug === state.selectedTeamSlug ? "−" : "+"}</span>
            </div>
          </button>
          ${
            team.slug === state.selectedTeamSlug
              ? `
              <div class="team-card-body">
                <div class="player-list">
                  ${team.players
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
      `
    )
    .join("");

  teamsViewEl.innerHTML = `
    <div class="team-list-shell">
      <div class="team-list-header">
        <p class="team-card-subtitle">Choose a club to expand its squad.</p>
      </div>
      <div class="team-list">${teamCards}</div>
    </div>
  `;

  teamsViewEl.querySelectorAll("[data-team-slug]").forEach((button) => {
    button.addEventListener("click", () => {
      const { teamSlug, playerId } = button.dataset;
      if (playerId) {
        openPlayer(teamSlug, playerId);
        return;
      }
      state.selectedTeamSlug = teamSlug;
      renderTeams();
      teamsViewEl.querySelector(`[data-team-slug="${teamSlug}"]`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  });
}

function renderView() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.view === state.view);
  });
  tableViewEl.classList.toggle("hidden", state.view !== "table");
  teamsViewEl.classList.toggle("hidden", state.view !== "teams");
  leagueSummaryEl.classList.toggle("hidden", state.view !== "table");

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
  dialogBodyEl.innerHTML = `
    <div class="player-dialog-panel">
      <p class="eyebrow">${team.club}</p>
      <h2 class="club-name">${player.name}</h2>
      <p class="subtitle">
        ${player.position || "Unknown role"}${
          player.shirtNumber ? ` · #${player.shirtNumber}` : ""
        }
      </p>
      <div class="stats-grid">
        ${[
          buildStatCard("Played", stats.played),
          buildStatCard("Goals", stats.goals),
          buildStatCard("Assists", stats.assists),
          buildStatCard("Minutes", stats.minutes),
          buildStatCard("Yellow", stats.yellowCards),
          buildStatCard("Red", stats.redCards),
          buildStatCard("Conceded", stats.conceded),
          buildStatCard("Clean Sheets", stats.cleanSheets),
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

async function selectLeague(leagueKey) {
  state.selectedLeague = leagueKey;
  renderLeaguePicker();

  const snapshot = await apiFetch(`/api/leagues/${leagueKey}/snapshot`);
  state.snapshot = snapshot;
  state.selectedTeamSlug = snapshot.teams[0]?.slug || null;
  leagueContentEl.classList.remove("hidden");
  renderSummary();
  renderView();
}

async function boot() {
  tg?.ready();
  tg?.expand();

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.view = tab.dataset.view;
      renderView();
    });
  });

  const leagueResponse = await apiFetch("/api/leagues");
  state.leagues = leagueResponse.leagues;
  renderLeaguePicker();

  const initialLeague = getQueryLeague() || state.leagues[0]?.key;
  if (initialLeague) {
    await selectLeague(initialLeague);
  }
}

boot().catch((error) => {
  leagueContentEl.classList.remove("hidden");
  tableViewEl.innerHTML = `<div class="empty-state">Could not load snapshot data: ${error.message}</div>`;
});
