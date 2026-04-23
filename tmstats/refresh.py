import argparse
import re
import time
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from lxml import html

from .catalog import LEAGUES, LEAGUE_KEYS
from .identity import canonical_club_identity, club_identity, normalize_text
from .incremental import detect_updated_match_clubs, resolve_team_names
from .pdf_export import render_pdf
from .refresh_paths import LeagueRefreshPaths, build_league_refresh_paths
from .refresh_state import write_refresh_state
from .source import (build_session, fetch_current_table, fetch_json,
                     fetch_knockout_bracket, fetch_match_groups,
                     fetch_recent_form, fetch_text)
from .storage import read_csv_rows, read_json, write_csv, write_json

DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25

PLAYER_FIELDS = ['id', 'name', 'shirtNumber', 'positionId',
                 'position', 'club', 'link']
STATS_FIELDS = ['player_id', 'player_name', 'number', 'position',
                'club', 'league',
                'played', 'goals', 'assists',
                'yellow_cards', 'second_yellows', 'red_cards',
                'conceded', 'clean_sheets',
                'minutes']
STAT_VALUE_FIELDS = ['played', 'goals', 'assists',
                     'yellow_cards', 'second_yellows', 'red_cards',
                     'conceded', 'clean_sheets', 'minutes']
TABLE_FIELDS = ['rank', 'club', 'logo', 'played', 'wins', 'draws',
                'losses', 'goals', 'diff', 'points', 'form']

POSITION_LABELS = {
    1: 'Goalkeeper',
    2: 'Defender',
    3: 'Midfield',
    4: 'Forward',
}


def current_season_start_year(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def stats_rows_with_values(rows: List[dict]) -> int:
    count = 0
    for row in rows:
        if any(normalize_text(row.get(field, '')) for field in STAT_VALUE_FIELDS):
            count += 1
    return count


def pick_stats_output(candidate_rows: List[dict],
                      existing_rows: List[dict],
                      league_key: str) -> List[dict]:
    candidate_count = stats_rows_with_values(candidate_rows)
    existing_count = stats_rows_with_values(existing_rows)

    if candidate_rows and candidate_count == 0 and existing_count > 0:
        print(
            f'Warning: preserving existing stats snapshot for {league_key} '
            f'because the refreshed player stats came back empty.',
            flush=True,
        )
        return existing_rows

    return candidate_rows


def render_snapshot_pdf(path: Path, snapshot_type: str,
                        league_label: str, season: int,
                        rows: List[dict],
                        data_changed: bool = False,
                        force: bool = False) -> bool:
    if not force and not data_changed and path.exists():
        return False
    render_pdf(path, snapshot_type, league_label, season, rows)
    return True


def build_refresh_result(league_key: str, season: int, *,
                         clubs: int, players: int,
                         stats_rows: int, table_rows: int) -> dict:
    return {
        'league': league_key,
        'season': season,
        'clubs': clubs,
        'players': players,
        'stats_rows': stats_rows,
        'table_rows': table_rows,
    }


def refresh_live_table(session: requests.Session, league_key: str,
                       season: int, timeout: int) -> Tuple[object, str, List[dict], List[dict]]:
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


def load_existing_players(path: Path) -> List[dict]:
    if not path.exists():
        return []

    players = read_csv_rows(path)
    return [
        {
            'id': normalize_text(player.get('id')),
            'name': normalize_text(player.get('name')),
            'shirtNumber': normalize_text(player.get('shirtNumber')),
            'positionId': normalize_text(player.get('positionId')),
            'position': normalize_text(player.get('position')),
            'club': normalize_text(player.get('club')),
            'link': normalize_text(player.get('link')),
        }
        for player in players
        if normalize_text(player.get('id')) and normalize_text(player.get('link'))
    ]


def replace_players_for_clubs(existing_players: List[dict],
                              replacement_players: List[dict],
                              club_ids: Iterable[str]) -> List[dict]:
    targeted = set(club_ids)
    preserved = [
        player for player in existing_players
        if canonical_club_identity(player.get('club', '')) not in targeted
    ]
    return preserved + replacement_players


def replace_stats_for_clubs(existing_rows: List[dict],
                            replacement_rows: List[dict],
                            club_ids: Iterable[str]) -> List[dict]:
    targeted = set(club_ids)
    preserved = [
        row for row in existing_rows
        if canonical_club_identity(row.get('club', '')) not in targeted
    ]
    return preserved + replacement_rows


def progress_bar(current: int, total: int, width: int = 22) -> str:
    if total <= 0:
        return '[' + ('-' * width) + ']'

    filled = min(width, round((current / total) * width))
    return '[' + ('#' * filled) + ('-' * (width - filled)) + ']'


def format_progress(prefix: str, current: int, total: int,
                    team_name: str = '', team_index: int = None,
                    team_total: int = None) -> str:
    percent = 0 if total <= 0 else round((current / total) * 100)
    line = (
        f'  {prefix} {progress_bar(current, total)} '
        f'{current}/{total} ({percent}%)'
    )
    if team_name:
        if team_index is not None and team_total:
            line += f' | club {team_index}/{team_total}: {team_name}'
        else:
            line += f' | club: {team_name}'
    return line


def fetch_players(session: requests.Session, teams: List[dict],
                  timeout: int, delay: float = DEFAULT_DELAY) -> List[dict]:
    players = []
    total_teams = len(teams)

    for index, team in enumerate(teams, start=1):
        print(
            format_progress('roster', index, total_teams, team['name'], index,
                            total_teams),
            flush=True,
        )
        url = f'https://www.transfermarkt.com/quickselect/players/{team["id"]}'
        team_players = fetch_json(session, url, timeout)
        for player in team_players:
            position_id = int(player['positionId'])
            players.append({
                'id': str(player['id']),
                'name': normalize_text(player['name']),
                'shirtNumber': normalize_text(player['shirtNumber']),
                'positionId': str(position_id),
                'position': POSITION_LABELS.get(position_id, 'Unknown'),
                'club': team['name'],
                'link': normalize_text(player['link']),
            })
        if delay:
            time.sleep(delay)

    print(
        f'  roster complete | collected {len(players)} players from '
        f'{total_teams} clubs',
        flush=True,
    )

    return players


def extract_position_label(doc: html.HtmlElement) -> str:
    labels = doc.xpath(
        '//li[contains(@class, "data-header__label")]'
        '[contains(normalize-space(.), "Position:")]'
        '//span[contains(@class, "data-header__content")]//text()'
    )
    return normalize_text(' '.join(labels))


def extract_stats_rows(doc: html.HtmlElement) -> List[List[str]]:
    rows = doc.xpath(
        '//table['
        './/th[contains(normalize-space(.), "Competition")]'
        ' or .//th[contains(normalize-space(.), "Wettbewerb")]'
        ']//tbody/tr[td]'
    )
    return [
        [normalize_text(' '.join(cell.xpath('.//text()'))) for cell in row.xpath('./td')]
        for row in rows
    ]


def competition_identity(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', normalize_text(value).casefold())


LEAGUE_ROW_ALIASES = {
    'epl': {'premierleague'},
    'la_liga': {'laliga'},
    'serie_a': {'seriea'},
    'bundesliga': {'bundesliga'},
    'ligue_1': {'ligue1'},
    'rpl': {'premierliga', 'russianpremierleague'},
    'ucl': {'championsleague'},
    'uel': {'europaleague'},
    'uecl': {'conferenceleague', 'uefaconferenceleague'},
}


def pick_stats_row(doc: html.HtmlElement, league_key: str) -> List[str]:
    league = LEAGUES[league_key]
    target_site_id = league.site_id.casefold()
    target_names = {
        competition_identity(league.label),
        competition_identity(league.button_label),
        competition_identity(league.table_slug.replace('-', ' ')),
        *LEAGUE_ROW_ALIASES.get(league_key, set()),
    }

    parsed_rows = []
    rows = doc.xpath(
        '//table['
        './/th[contains(normalize-space(.), "Competition")]'
        ' or .//th[contains(normalize-space(.), "Wettbewerb")]'
        ']//tbody/tr[td]'
    )
    parsed_cells = extract_stats_rows(doc)

    for row, cells in zip(rows, parsed_cells):
        hrefs = [
            href.casefold()
            for href in row.xpath('.//a[contains(@href, "/wettbewerb/")]/@href')
        ]
        parsed_rows.append((cells, hrefs))

        if any(f'/wettbewerb/{target_site_id}' in href for href in hrefs):
            return cells

    for cells, _hrefs in parsed_rows:
        identities = {
            competition_identity(cells[index])
            for index in range(min(2, len(cells)))
            if cells[index]
        }
        if identities & target_names:
            return cells

    return []


def build_player_stats(player: dict, cells: List[str], league_label: str,
                       position_label: str) -> dict:
    number = f'#{player["shirtNumber"]}' if player['shirtNumber'] else ''
    stats = {
        'player_id': player['id'],
        'player_name': player['name'],
        'number': number,
        'position': position_label or player['position'],
        'club': player['club'],
        'league': cells[1] if len(cells) > 1 and cells[1] else league_label,
        'played': cells[2] if len(cells) > 2 else '',
        'goals': cells[3] if len(cells) > 3 else '',
        'assists': '',
        'yellow_cards': '',
        'second_yellows': '',
        'red_cards': '',
        'conceded': '',
        'clean_sheets': '',
        'minutes': '',
    }

    if player['positionId'] == '1':
        stats.update({
            'yellow_cards': cells[4] if len(cells) > 4 else '',
            'second_yellows': cells[5] if len(cells) > 5 else '',
            'red_cards': cells[6] if len(cells) > 6 else '',
            'conceded': cells[7] if len(cells) > 7 else '',
            'clean_sheets': cells[8] if len(cells) > 8 else '',
            'minutes': cells[9] if len(cells) > 9 else '',
        })
    else:
        stats.update({
            'assists': cells[4] if len(cells) > 4 else '',
            'yellow_cards': cells[5] if len(cells) > 5 else '',
            'second_yellows': cells[6] if len(cells) > 6 else '',
            'red_cards': cells[7] if len(cells) > 7 else '',
            'minutes': cells[8] if len(cells) > 8 else '',
        })

    return stats


def fetch_stats(session: requests.Session, league_key: str, players: List[dict],
                season: int, timeout: int,
                teams: List[dict] = None,
                delay: float = DEFAULT_DELAY) -> List[dict]:
    league_label = LEAGUES[league_key].label
    stats_rows = []
    team_order = {
        team['name']: index
        for index, team in enumerate(teams or [], start=1)
    }
    team_total = len(teams or [])
    last_team = None

    for index, player in enumerate(players, start=1):
        current_team = player['club']
        current_team_index = team_order.get(current_team)
        if current_team != last_team:
            print(
                format_progress(
                    'stats',
                    index - 1,
                    len(players),
                    current_team,
                    current_team_index,
                    team_total,
                ),
                flush=True,
            )
            last_team = current_team

        slug = player['link'].split('/')[1]
        url = (
            f'https://www.transfermarkt.com/{slug}/leistungsdaten/'
            f'spieler/{player["id"]}/plus/0?saison={season}'
        )
        try:
            doc = html.fromstring(fetch_text(session, url, timeout))
            cells = pick_stats_row(doc, league_key)
            position_label = extract_position_label(doc)
            if not cells:
                print(
                    f'Warning: no {league_key} competition row found for '
                    f'{player["name"]} ({player["id"]})',
                    flush=True,
                )
        except (requests.RequestException, RuntimeError) as error:
            print(f'Warning: failed to refresh stats for {player["name"]}: '
                  f'{error}', flush=True)
            cells = []
            position_label = player['position']

        stats_rows.append(
            build_player_stats(player, cells, league_label, position_label)
        )

        if index % 25 == 0 or index == len(players):
            print(
                format_progress(
                    'stats',
                    index,
                    len(players),
                    current_team,
                    current_team_index,
                    team_total,
                ),
                flush=True,
            )

        if delay:
            time.sleep(delay)

    print(
        f'  stats complete | wrote {len(stats_rows)} player rows for '
        f'{league_key}',
        flush=True,
    )

    return stats_rows


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
        players_changed = write_csv(paths.players_csv, players, PLAYER_FIELDS)
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

    stats_changed = write_csv(paths.stats_csv, stats_output, STATS_FIELDS)
    table_changed = write_csv(paths.table_csv, table, TABLE_FIELDS)
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
        matches_changed = write_json(
            paths.matches_json,
            matches_payload,
        )
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: '
              f'{error}', flush=True)
    table_pdf_rendered = render_snapshot_pdf(
        paths.table_pdf,
        'table',
        league_label,
        season,
        table,
        data_changed=table_changed,
    )
    stats_pdf_rendered = render_snapshot_pdf(
        paths.stats_pdf,
        'stats',
        league_label,
        season,
        stats_output,
        data_changed=stats_changed,
    )
    write_refresh_state(
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

    return build_refresh_result(
        league_key,
        season,
        clubs=len(teams),
        players=len(players),
        stats_rows=len(stats_output),
        table_rows=len(table),
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

    table_pdf_rendered = render_snapshot_pdf(
        paths.table_pdf,
        'table',
        league_label,
        season,
        table_rows,
        force=True,
    )
    stats_pdf_rendered = render_snapshot_pdf(
        paths.stats_pdf,
        'stats',
        league_label,
        season,
        stats_rows,
        force=True,
    )
    matches_payload = read_json(paths.matches_json) if paths.matches_json.exists() else None
    write_refresh_state(
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

    return build_refresh_result(
        league_key,
        season,
        clubs=len(table_rows),
        players=len(stats_rows),
        stats_rows=len(stats_rows),
        table_rows=len(table_rows),
    )


def refresh_leagues(league_keys: Iterable[str], season: int = None,
                    timeout: int = DEFAULT_TIMEOUT,
                    delay: float = DEFAULT_DELAY,
                    refresh_rosters: bool = False) -> List[dict]:
    results = []
    for league_key in league_keys:
        results.append(refresh_league(league_key, season, timeout, delay,
                                      refresh_rosters))
    return results


def refresh_changed_team_stats_only(
        league_key: str, season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> dict:
    """Refresh table/matches, then update stats only for clubs in changed matches."""
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

    matches_changed = write_json(paths.matches_json, latest_matches)
    table_changed = write_csv(paths.table_csv, table, TABLE_FIELDS)
    table_pdf_rendered = render_snapshot_pdf(
        paths.table_pdf,
        'table',
        league_label,
        season,
        table,
        data_changed=table_changed,
    )

    if not changed_clubs:
        print('  no newly completed or changed matches; player stats unchanged',
              flush=True)
        write_refresh_state(
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
        return build_refresh_result(
            league_key,
            season,
            clubs=len(teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(table),
        )

    targeted_teams, unresolved_clubs = resolve_team_names(changed_clubs, teams)
    targeted_team_ids = {
        canonical_club_identity(team.get('name', ''))
        for team in targeted_teams
    }

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
        write_refresh_state(
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
        return build_refresh_result(
            league_key,
            season,
            clubs=len(teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(table),
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
    players_changed = write_csv(paths.players_csv, players_output, PLAYER_FIELDS)

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
    stats_changed = write_csv(paths.stats_csv, stats_output, STATS_FIELDS)
    stats_pdf_rendered = render_snapshot_pdf(
        paths.stats_pdf,
        'stats',
        league_label,
        season,
        stats_output,
        data_changed=stats_changed,
    )
    write_refresh_state(
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

    return build_refresh_result(
        league_key,
        season,
        clubs=len(teams),
        players=len(players_output),
        stats_rows=len(stats_output),
        table_rows=len(table),
    )


def refresh_matches_only(league_key: str, season: int = None,
                         timeout: int = DEFAULT_TIMEOUT,
                         delay: float = DEFAULT_DELAY) -> dict:
    """Refresh only match/bracket JSON snapshots (no roster or player stats)."""
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
        matches_changed = write_json(
            paths.matches_json,
            matches_payload,
        )
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: {error}', flush=True)
    write_refresh_state(
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

    return build_refresh_result(
        league_key,
        season,
        clubs=len(table),
        players=0,
        stats_rows=0,
        table_rows=len(table),
    )


def refresh_matches_for_leagues(league_keys: Iterable[str], season: int = None,
                                timeout: int = DEFAULT_TIMEOUT,
                                delay: float = DEFAULT_DELAY) -> List[dict]:
    results = []
    for league_key in league_keys:
        print(f'Refreshing match snapshots for {league_key} season {season}', flush=True)
        results.append(refresh_matches_only(league_key, season, timeout, delay))
    return results


def refresh_changed_team_stats_for_leagues(
        league_keys: Iterable[str], season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> List[dict]:
    results = []
    for league_key in league_keys:
        results.append(
            refresh_changed_team_stats_only(
                league_key,
                season,
                timeout,
                delay,
            )
        )
    return results


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

    table_changed = write_csv(paths.table_csv, updated_rows, TABLE_FIELDS)
    table_pdf_rendered = render_snapshot_pdf(
        paths.table_pdf,
        'table',
        LEAGUES[league_key].label,
        season,
        updated_rows,
        data_changed=table_changed,
    )
    matches_payload = read_json(paths.matches_json) if paths.matches_json.exists() else None
    write_refresh_state(
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

    return build_refresh_result(
        league_key,
        season,
        clubs=len(updated_rows),
        players=0,
        stats_rows=0,
        table_rows=len(updated_rows),
    )


def refresh_logos_for_leagues(league_keys: Iterable[str],
                              season: int = None,
                              timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    results = []
    for league_key in league_keys:
        print(f'Refreshing logos for {league_key} season {season}', flush=True)
        results.append(refresh_logos_only(league_key, season, timeout))
    return results


def render_pdfs_for_leagues(league_keys: Iterable[str],
                            season: int = None) -> List[dict]:
    results = []
    for league_key in league_keys:
        print(f'Rendering PDFs for {league_key} season {season}', flush=True)
        results.append(render_league_pdfs(league_key, season))
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Refresh current Transfermarkt snapshots for one or more leagues.'
    )
    parser.add_argument(
        '--league',
        action='append',
        choices=sorted(LEAGUE_KEYS),
        help='League key to refresh. Repeat the flag to refresh multiple leagues.',
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Refresh all supported leagues.',
    )
    parser.add_argument(
        '--season',
        type=int,
        default=current_season_start_year(),
        help='Transfermarkt season start year. Defaults to the current European season.',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=DEFAULT_TIMEOUT,
        help='HTTP timeout in seconds for each request.',
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=DEFAULT_DELAY,
        help='Optional delay in seconds between requests.',
    )
    parser.add_argument(
        '--pdf-only',
        action='store_true',
        help='Generate PDFs from existing CSV snapshots without refreshing data.',
    )
    parser.add_argument(
        '--matches-only',
        action='store_true',
        help='Refresh match/bracket JSON snapshots without scraping players.',
    )
    parser.add_argument(
        '--changed-team-stats',
        action='store_true',
        help=(
            'Refresh table/matches, then scrape only clubs involved in newly '
            'completed or changed matches.'
        ),
    )
    parser.add_argument(
        '--logos-only',
        action='store_true',
        help='Refresh only team logo URLs in existing table CSV snapshots.',
    )
    parser.add_argument(
        '--refresh-rosters',
        action='store_true',
        help='Force a fresh roster pull instead of reusing the saved players CSV.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    league_keys = args.league or []

    if args.all or not league_keys:
        league_keys = list(LEAGUE_KEYS)

    if args.logos_only:
        results = refresh_logos_for_leagues(league_keys,
                                            season=args.season,
                                            timeout=args.timeout)
        completion_label = 'Logo refresh complete'
    elif args.changed_team_stats:
        results = refresh_changed_team_stats_for_leagues(
            league_keys,
            season=args.season,
            timeout=args.timeout,
            delay=args.delay,
        )
        completion_label = 'Changed-team refresh complete'
    elif args.pdf_only:
        results = render_pdfs_for_leagues(league_keys, season=args.season)
        completion_label = 'PDF render complete'
    elif args.matches_only:
        results = refresh_matches_for_leagues(league_keys,
                                              season=args.season,
                                              timeout=args.timeout,
                                              delay=args.delay)
        completion_label = 'Match snapshot refresh complete'
    else:
        results = refresh_leagues(league_keys,
                                  season=args.season,
                                  timeout=args.timeout,
                                  delay=args.delay,
                                  refresh_rosters=args.refresh_rosters)
        completion_label = 'Refresh complete'

    print()
    print(completion_label)
    for result in results:
        print(
            f'- {result["league"]}: '
            f'{result["clubs"]} clubs, '
            f'{result["players"]} players, '
            f'{result["stats_rows"]} stats rows, '
            f'{result["table_rows"]} table rows'
        )


if __name__ == '__main__':
    main()
