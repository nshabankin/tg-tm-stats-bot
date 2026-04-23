from datetime import date
from typing import List, Optional, Tuple

import requests

from .catalog import LEAGUES
from .identity import canonical_club_identity, club_identity
from .incremental import detect_updated_match_clubs, resolve_team_names
from .player_stats import (fetch_players, fetch_stats, load_existing_players,
                           pick_stats_output, replace_players_for_clubs,
                           replace_stats_for_clubs)
from .refresh_pipeline import (render_snapshot_pdfs, write_matches_snapshot,
                               write_players_snapshot,
                               write_refresh_summary, write_stats_snapshot,
                               write_table_snapshot)
from .refresh_paths import LeagueRefreshPaths, build_league_refresh_paths
from .source import (build_session, fetch_current_table,
                     fetch_knockout_bracket, fetch_match_groups,
                     fetch_recent_form)
from .storage import read_csv_rows, read_json, write_json

DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25


def current_season_start_year(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def refresh_live_table(session: requests.Session, league_key: str,
                       season: int,
                       timeout: int) -> Tuple[object, str, List[dict], List[dict]]:
    league = LEAGUES[league_key]
    league_label = league.label
    teams, table = fetch_current_table(session, league_key, season, timeout)
    try:
        recent_form = fetch_recent_form(session, league_key, season, timeout)
    except Exception as error:
        print(f'Warning: failed to refresh recent form for {league_key}: '
              f'{error}', flush=True)
        recent_form = {}

    for team, table_row in zip(teams, table):
        form_value = recent_form.get(team['id'], '')
        team['form'] = form_value
        table_row['form'] = form_value

    return league, league_label, teams, table


def refresh_bracket_snapshot(session: requests.Session,
                             league_key: str,
                             season: int,
                             timeout: int,
                             paths: LeagueRefreshPaths) -> Tuple[Optional[dict], bool]:
    if not LEAGUES[league_key].supports_bracket:
        return None, False

    try:
        bracket_payload = fetch_knockout_bracket(session, league_key, season, timeout)
        bracket_changed = write_json(paths.bracket_json, bracket_payload)
        return bracket_payload, bracket_changed
    except Exception as error:
        print(f'Warning: failed to refresh knockout bracket for {league_key}: '
              f'{error}', flush=True)
        return None, False


def refresh_league(league_key: str, season: int = None,
                   timeout: int = DEFAULT_TIMEOUT,
                   delay: float = DEFAULT_DELAY,
                   refresh_rosters: bool = False) -> dict:
    season = season or current_season_start_year()
    session = build_session()
    paths = build_league_refresh_paths(league_key, season)

    print(f'Refreshing {league_key} for season {season}', flush=True)

    _league, league_label, teams, table = refresh_live_table(
        session,
        league_key,
        season,
        timeout,
    )

    players = []
    players_changed = False
    if not refresh_rosters:
        players = load_existing_players(paths.players_csv)
        if players:
            print(f'  reusing {len(players)} players from saved roster',
                  flush=True)

    if not players:
        players = fetch_players(session, teams, timeout, delay)
        players_changed = write_players_snapshot(paths, players)
        print(f'  fetched {len(teams)} teams and {len(players)} players',
              flush=True)

    stats = fetch_stats(
        session,
        league_key,
        players,
        season,
        timeout,
        teams=teams,
        delay=delay,
    )

    existing_stats = read_csv_rows(paths.stats_csv) if paths.stats_csv.exists() else []
    stats_output = pick_stats_output(stats, existing_stats, league_key)

    stats_changed = write_stats_snapshot(paths, stats_output)
    table_changed = write_table_snapshot(paths, table)
    bracket_payload, bracket_changed = refresh_bracket_snapshot(
        session,
        league_key,
        season,
        timeout,
        paths,
    )

    matches_payload = None
    matches_changed = False
    try:
        matches_payload = fetch_match_groups(
            session,
            league_key,
            season,
            timeout,
            bracket=bracket_payload,
            teams=teams,
            club_count=len(table),
            delay=delay,
        )
        matches_changed = write_matches_snapshot(paths, matches_payload)
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: '
              f'{error}', flush=True)
    table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        paths,
        league_label,
        season,
        table_rows=table,
        stats_rows=stats_output,
        table_changed=table_changed,
        stats_changed=stats_changed,
    )

    return write_refresh_summary(
        league_key,
        season,
        mode='full',
        clubs=len(teams),
        players=len(players),
        stats_rows=len(stats_output),
        table_rows=len(table),
        matches_payload=matches_payload,
        stats_status='preserved' if stats_output == existing_stats else 'refreshed',
        table_changed=table_changed,
        players_changed=players_changed,
        stats_changed=stats_changed,
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def render_league_pdfs(league_key: str, season: int = None) -> dict:
    season = season or current_season_start_year()
    paths = build_league_refresh_paths(league_key, season)
    league_label = LEAGUES[league_key].label

    missing = [path.name for path in (paths.table_csv, paths.stats_csv)
               if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f'Missing CSV snapshots for {league_key} season {season}: '
            f'{", ".join(missing)}'
        )

    table_rows = read_csv_rows(paths.table_csv)
    stats_rows = read_csv_rows(paths.stats_csv)
    table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        paths,
        league_label,
        season,
        table_rows=table_rows,
        stats_rows=stats_rows,
        force=True,
    )
    matches_payload = read_json(paths.matches_json) if paths.matches_json.exists() else None

    return write_refresh_summary(
        league_key,
        season,
        mode='pdf-only',
        clubs=len(table_rows),
        players=len(stats_rows),
        stats_rows=len(stats_rows),
        table_rows=len(table_rows),
        matches_payload=matches_payload,
        stats_status='unchanged',
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def refresh_changed_team_stats_only(
        league_key: str, season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> dict:
    season = season or current_season_start_year()
    paths = build_league_refresh_paths(league_key, season)

    if not (paths.players_csv.exists() and paths.stats_csv.exists() and paths.matches_json.exists()):
        print(
            f'Refreshing changed-team stats for {league_key} for season {season}',
            flush=True,
        )
        print(
            '  missing baseline snapshots; falling back to a full league refresh',
            flush=True,
        )
        return refresh_league(league_key, season, timeout, delay)

    session = build_session()
    print(f'Refreshing changed-team stats for {league_key} for season {season}',
          flush=True)

    existing_matches = read_json(paths.matches_json)
    existing_players = load_existing_players(paths.players_csv)
    existing_stats = read_csv_rows(paths.stats_csv)

    _league, league_label, teams, table = refresh_live_table(
        session,
        league_key,
        season,
        timeout,
    )
    bracket_payload, bracket_changed = refresh_bracket_snapshot(
        session,
        league_key,
        season,
        timeout,
        paths,
    )

    latest_matches = fetch_match_groups(
        session,
        league_key,
        season,
        timeout,
        bracket=bracket_payload,
        teams=teams,
        club_count=len(table),
        existing_payload=existing_matches,
        delay=delay,
    )
    changed_clubs = detect_updated_match_clubs(existing_matches, latest_matches)

    matches_changed = write_matches_snapshot(paths, latest_matches)
    table_changed = write_table_snapshot(paths, table)
    table_pdf_rendered, _stats_pdf_rendered = render_snapshot_pdfs(
        paths,
        league_label,
        season,
        table_rows=table,
        table_changed=table_changed,
    )

    if not changed_clubs:
        print('  no newly completed or changed matches; player stats unchanged',
              flush=True)
        return write_refresh_summary(
            league_key,
            season,
            mode='changed-team-stats',
            clubs=len(teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(table),
            matches_payload=latest_matches,
            stats_status='skipped',
            table_changed=table_changed,
            stats_changed=False,
            matches_changed=matches_changed,
            bracket_changed=bracket_changed,
            table_pdf_rendered=table_pdf_rendered,
        )

    targeted_teams, unresolved_clubs = resolve_team_names(changed_clubs, teams)

    if unresolved_clubs:
        print(
            f'  could not map changed match clubs for {league_key}; '
            f'{", ".join(unresolved_clubs)}',
            flush=True,
        )
        print('  player stats unchanged for unmatched clubs', flush=True)

    if not targeted_teams:
        print('  no changed clubs could be resolved to current table teams',
              flush=True)
        return write_refresh_summary(
            league_key,
            season,
            mode='changed-team-stats',
            clubs=len(teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(table),
            matches_payload=latest_matches,
            changed_clubs=changed_clubs,
            unresolved_clubs=unresolved_clubs,
            stats_status='unresolved',
            table_changed=table_changed,
            stats_changed=False,
            matches_changed=matches_changed,
            bracket_changed=bracket_changed,
            table_pdf_rendered=table_pdf_rendered,
        )

    print(
        f'  refreshing players/stats for {len(targeted_teams)} club(s): '
        f'{", ".join(team["name"] for team in targeted_teams)}',
        flush=True,
    )

    replacement_players = fetch_players(session, targeted_teams, timeout, delay)
    targeted_club_ids = {
        canonical_club_identity(team.get('name', ''))
        for team in targeted_teams
    }
    players_output = replace_players_for_clubs(
        existing_players,
        replacement_players,
        targeted_club_ids,
    )
    players_changed = write_players_snapshot(paths, players_output)

    targeted_existing_stats = [
        row for row in existing_stats
        if canonical_club_identity(row.get('club', '')) in targeted_club_ids
    ]
    replacement_stats = fetch_stats(
        session,
        league_key,
        replacement_players,
        season,
        timeout,
        teams=teams,
        delay=delay,
    )
    replacement_stats = pick_stats_output(
        replacement_stats,
        targeted_existing_stats,
        league_key,
    )
    stats_output = replace_stats_for_clubs(
        existing_stats,
        replacement_stats,
        targeted_club_ids,
    )
    stats_changed = write_stats_snapshot(paths, stats_output)
    _table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        paths,
        league_label,
        season,
        stats_rows=stats_output,
        stats_changed=stats_changed,
    )
    return write_refresh_summary(
        league_key,
        season,
        mode='changed-team-stats',
        clubs=len(teams),
        players=len(players_output),
        stats_rows=len(stats_output),
        table_rows=len(table),
        matches_payload=latest_matches,
        changed_clubs=changed_clubs,
        resolved_clubs=[team.get('name', '') for team in targeted_teams],
        unresolved_clubs=unresolved_clubs,
        stats_status='preserved' if stats_output == existing_stats else 'targeted',
        table_changed=table_changed,
        players_changed=players_changed,
        stats_changed=stats_changed,
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def refresh_matches_only(league_key: str, season: int = None,
                         timeout: int = DEFAULT_TIMEOUT,
                         delay: float = DEFAULT_DELAY) -> dict:
    season = season or current_season_start_year()
    session = build_session()
    paths = build_league_refresh_paths(league_key, season)
    existing_matches = read_json(paths.matches_json) if paths.matches_json.exists() else None

    _league, _league_label, teams, table = refresh_live_table(
        session,
        league_key,
        season,
        timeout,
    )

    bracket_payload, bracket_changed = refresh_bracket_snapshot(
        session,
        league_key,
        season,
        timeout,
        paths,
    )

    matches_payload = existing_matches
    matches_changed = False
    try:
        matches_payload = fetch_match_groups(
            session,
            league_key,
            season,
            timeout,
            bracket=bracket_payload,
            teams=teams,
            club_count=len(table),
            existing_payload=existing_matches,
            delay=delay,
        )
        matches_changed = write_matches_snapshot(paths, matches_payload)
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: {error}', flush=True)

    return write_refresh_summary(
        league_key,
        season,
        mode='matches-only',
        clubs=len(table),
        players=0,
        stats_rows=0,
        table_rows=len(table),
        matches_payload=matches_payload,
        stats_status='skipped',
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
    )


def refresh_logos_only(league_key: str, season: int = None,
                       timeout: int = DEFAULT_TIMEOUT) -> dict:
    season = season or current_season_start_year()
    paths = build_league_refresh_paths(league_key, season)
    if not paths.table_csv.exists():
        raise FileNotFoundError(
            f'Missing table snapshot for {league_key} season {season}: '
            f'{paths.table_csv.name}'
        )

    session = build_session()
    _, latest_table = fetch_current_table(session, league_key, season, timeout)
    latest_by_club = {club_identity(row['club']): row for row in latest_table}
    latest_by_rank = {row['rank']: row for row in latest_table}
    current_rows = read_csv_rows(paths.table_csv)

    updated_rows = []
    for row in current_rows:
        latest = latest_by_club.get(club_identity(row.get('club', '')))
        if not latest:
            latest = latest_by_rank.get(row.get('rank', ''))
        updated_rows.append({
            **row,
            'logo': latest.get('logo', '') if latest else row.get('logo', ''),
        })

    table_changed = write_table_snapshot(paths, updated_rows)
    table_pdf_rendered, _stats_pdf_rendered = render_snapshot_pdfs(
        paths,
        LEAGUES[league_key].label,
        season,
        table_rows=updated_rows,
        table_changed=table_changed,
    )
    matches_payload = read_json(paths.matches_json) if paths.matches_json.exists() else None

    return write_refresh_summary(
        league_key,
        season,
        mode='logos-only',
        clubs=len(updated_rows),
        players=0,
        stats_rows=0,
        table_rows=len(updated_rows),
        matches_payload=matches_payload,
        stats_status='skipped',
        table_changed=table_changed,
        table_pdf_rendered=table_pdf_rendered,
    )
