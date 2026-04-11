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
    <div class="table-grid">
      ${state.snapshot.table
        .map(
          (row) => `
          <article class="table-card">
            <div class="table-card-header">
              <div>
                <span class="rank-badge">${row.rank}</span>
                <h3 class="club-name">${row.club}</h3>
              </div>
              <div class="points">${row.points} pts</div>
            </div>
            <div class="meta-line">
              <span>P ${row.played}</span>
              <span>W ${row.wins}</span>
              <span>D ${row.draws}</span>
              <span>L ${row.losses}</span>
              <span>GF:GA ${row.goals}</span>
              <span>GD ${row.diff}</span>
            </div>
            <div class="form-row">
              <span class="team-card-subtitle">Recent form</span>
              ${renderFormPills(row.form)}
            </div>
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
        <button
          type="button"
          class="team-card ${team.slug === state.selectedTeamSlug ? "is-active" : ""}"
          data-team-slug="${team.slug}"
        >
          <div class="team-card-header">
            <div>
              <span class="rank-badge">${team.rank}</span>
              <h3 class="club-name">${team.club}</h3>
            </div>
            <div class="points">${team.points} pts</div>
          </div>
          <div class="record-line">
            <span>${team.wins}-${team.draws}-${team.losses}</span>
            <span>GF:GA ${team.goals}</span>
            <span>${team.playerCount} players</span>
          </div>
        </button>
      `
    )
    .join("");

  let detailMarkup = '<div class="empty-state">No team selected.</div>';
  if (selected) {
    detailMarkup = `
      <section class="team-detail">
        <div class="team-detail-header">
          <div>
            <span class="rank-badge">${selected.rank}</span>
            <h3 class="club-name">${selected.club}</h3>
          </div>
          <div class="points">${selected.points} pts</div>
        </div>
        <div class="meta-line">
          <span>Played ${selected.played}</span>
          <span>W ${selected.wins}</span>
          <span>D ${selected.draws}</span>
          <span>L ${selected.losses}</span>
          <span>GF:GA ${selected.goals}</span>
          <span>GD ${selected.diff}</span>
        </div>
        <div class="form-row">
          <span class="team-card-subtitle">Recent form</span>
          ${renderFormPills(selected.form)}
        </div>
        <p class="team-card-subtitle team-detail-note">Tap a player to open their stat card.</p>
        <div class="player-list">
          ${selected.players
            .map(
              (player) => `
                <button
                  type="button"
                  class="player-button"
                  data-team-slug="${selected.slug}"
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
      </section>
    `;
  }

  teamsViewEl.innerHTML = `
    <div class="team-list-shell">
      ${detailMarkup}
      <div class="team-list-header">
        <p class="team-card-subtitle">Choose a club from the standings list.</p>
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
      teamsViewEl.querySelector(".team-detail")?.scrollIntoView({
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
    <div>
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
