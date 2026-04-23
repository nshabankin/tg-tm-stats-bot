from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import requests

from .catalog import LEAGUES
from .refresh_paths import LeagueRefreshPaths, build_league_refresh_paths
from .source import build_session, fetch_current_table, fetch_recent_form

DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25


@dataclass
class RefreshContext:
    league_key: str
    season: int
    timeout: int
    paths: LeagueRefreshPaths
    league_label: str
    session: Optional[requests.Session] = None
    teams: List[dict] = field(default_factory=list)
    table: List[dict] = field(default_factory=list)


def current_season_start_year(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def build_refresh_context(league_key: str,
                          season: int = None,
                          timeout: int = DEFAULT_TIMEOUT,
                          with_session: bool = False,
                          with_live_table: bool = False) -> RefreshContext:
    resolved_season = season or current_season_start_year()
    league = LEAGUES[league_key]
    paths = build_league_refresh_paths(league_key, resolved_season)
    session = build_session() if with_session or with_live_table else None
    context = RefreshContext(
        league_key=league_key,
        season=resolved_season,
        timeout=timeout,
        paths=paths,
        league_label=league.label,
        session=session,
    )

    if with_live_table:
        refresh_live_table(context)

    return context


def refresh_live_table(context: RefreshContext) -> RefreshContext:
    if context.session is None:
        context.session = build_session()

    teams, table = fetch_current_table(
        context.session,
        context.league_key,
        context.season,
        context.timeout,
    )
    try:
        recent_form = fetch_recent_form(
            context.session,
            context.league_key,
            context.season,
            context.timeout,
        )
    except Exception as error:
        print(
            f'Warning: failed to refresh recent form for {context.league_key}: '
            f'{error}',
            flush=True,
        )
        recent_form = {}

    for team, table_row in zip(teams, table):
        form_value = recent_form.get(team['id'], '')
        team['form'] = form_value
        table_row['form'] = form_value

    context.teams = teams
    context.table = table
    return context
