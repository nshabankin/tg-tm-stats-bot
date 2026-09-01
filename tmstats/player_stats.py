import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from lxml import html

from .catalog import LEAGUES
from .identity import canonical_club_identity, normalize_text
from .source import (TransfermarktVerificationError, fetch_json, fetch_text)
from .storage import read_csv_rows

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

POSITION_LABELS = {
    1: 'Goalkeeper',
    2: 'Defender',
    3: 'Midfield',
    4: 'Forward',
}

LEAGUE_ROW_ALIASES = {
    'epl': {'premierleague'},
    'la_liga': {'laliga', 'laligaeasports', 'laligasantander'},
    'serie_a': {'seriea'},
    'bundesliga': {'bundesliga'},
    'ligue_1': {'ligue1'},
    'rpl': {'premierliga', 'russianpremierleague'},
    'ucl': {'championsleague'},
    'uel': {'europaleague'},
    'uecl': {'conferenceleague', 'uefaconferenceleague'},
    'world_cup': {'worldcup', 'fifaworldcup'},
}


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


def players_by_club_identity(players: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for player in players:
        club_id = canonical_club_identity(player.get('club', ''))
        if club_id:
            grouped.setdefault(club_id, []).append(player)
    return grouped


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
                  timeout: int, delay: float = 0.25,
                  existing_players: Optional[List[dict]] = None) -> List[dict]:
    players = []
    total_teams = len(teams)
    fallback_players = players_by_club_identity(existing_players or [])

    for index, team in enumerate(teams, start=1):
        print(
            format_progress('roster', index, total_teams, team['name'], index,
                            total_teams),
            flush=True,
        )
        url = f'https://www.transfermarkt.com/quickselect/players/{team["id"]}'
        try:
            team_players = fetch_json(session, url, timeout)
        except (requests.RequestException, ValueError) as error:
            club_id = canonical_club_identity(team.get('name', ''))
            preserved_players = fallback_players.get(club_id, [])
            if preserved_players:
                print(
                    f'Warning: preserving existing roster for {team["name"]} '
                    f'after roster fetch failed: {error}',
                    flush=True,
                )
                players.extend(preserved_players)
            else:
                print(
                    f'Warning: skipping roster for {team["name"]} after '
                    f'fetch failed and no saved roster was available: {error}',
                    flush=True,
                )
            if delay:
                time.sleep(delay)
            continue

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


def competition_matches_target(identities: set, target_names: set) -> bool:
    for identity in identities:
        for target in target_names:
            if not identity or not target:
                continue
            if identity == target:
                return True
            if identity.startswith(target) or target.startswith(identity):
                return True
    return False


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
        if competition_matches_target(identities, target_names):
            return cells

    return []


def format_stat_count(value: int) -> str:
    return str(value) if value else '-'


def format_minutes(value: int) -> str:
    if not value:
        return ''
    return f"{value:,}".replace(',', '.') + "'"


def numeric_stat(sections: Dict[str, Any], key: str) -> int:
    total = 0
    for values in sections.values():
        if not isinstance(values, dict) or key not in values:
            continue
        value = values[key]
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            total += int(value)
        elif isinstance(value, dict):
            total += 1
    return total


def fetch_performance_games(session: requests.Session, player_id: str,
                            timeout: int) -> List[dict]:
    url = f'https://www.transfermarkt.com/ceapi/performance-game/{player_id}'
    payload = fetch_json(session, url, timeout)
    if not isinstance(payload, dict) or not payload.get('success'):
        raise RuntimeError('Transfermarkt performance API returned no data')

    data = payload.get('data') or {}
    performances = data.get('performance') or []
    if not isinstance(performances, list):
        raise RuntimeError('Transfermarkt performance API returned invalid data')
    return performances


def build_player_stats_from_api(player: dict, performances: List[dict],
                                league_key: str, season: int,
                                league_label: str) -> Optional[dict]:
    league = LEAGUES[league_key]
    matching_games = [
        performance for performance in performances
        if (performance.get('gameInformation') or {}).get('competitionId') == league.site_id
        and (performance.get('gameInformation') or {}).get('seasonId') == season
    ]
    played_games = [
        game for game in matching_games
        if (
            ((game.get('statistics') or {}).get('playingTimeStatistics') or {})
            .get('playedMinutes') or 0
        ) > 0
        or (
            ((game.get('statistics') or {}).get('generalStatistics') or {})
            .get('participationState') == 'played'
        )
    ]
    if not played_games:
        return None

    played = len(played_games)
    goals = 0
    assists = 0
    yellow_cards = 0
    second_yellows = 0
    red_cards = 0
    conceded = 0
    clean_sheets = 0
    minutes = 0

    for game in played_games:
        stats = game.get('statistics') or {}
        goal_stats = stats.get('goalStatistics') or {}
        time_stats = stats.get('playingTimeStatistics') or {}
        clubs = game.get('clubsInformation') or {}
        club = clubs.get('club') or {}

        goals += int(goal_stats.get('goalsScoredTotal') or 0)
        assists += int(goal_stats.get('assists') or 0)
        yellow_cards += numeric_stat(stats, 'yellowCardNet')
        second_yellows += numeric_stat(stats, 'yellowRedCard')
        red_cards += numeric_stat(stats, 'redCard')
        minutes += int(time_stats.get('playedMinutes') or 0)

        if player['positionId'] == '1':
            conceded += int(goal_stats.get('opponentGoalsOnThePitch') or 0)
            if time_stats.get('playedMinutes') and club.get('opponentGoalsTotal') == 0:
                clean_sheets += 1

    row = {
        'player_id': player['id'],
        'player_name': player['name'],
        'number': f'#{player["shirtNumber"]}' if player['shirtNumber'] else '',
        'position': player['position'],
        'club': player['club'],
        'league': league_label,
        'played': str(played),
        'goals': format_stat_count(goals),
        'assists': format_stat_count(assists),
        'yellow_cards': format_stat_count(yellow_cards),
        'second_yellows': format_stat_count(second_yellows),
        'red_cards': format_stat_count(red_cards),
        'conceded': '',
        'clean_sheets': '',
        'minutes': format_minutes(minutes),
    }

    if player['positionId'] == '1':
        row.update({
            'assists': '',
            'conceded': format_stat_count(conceded),
            'clean_sheets': format_stat_count(clean_sheets),
        })

    return row


def index_existing_stats(existing_rows: List[dict]) -> Dict[str, dict]:
    return {
        normalize_text(row.get('player_id')): row
        for row in existing_rows or []
        if normalize_text(row.get('player_id'))
    }


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
                delay: float = 0.25,
                existing_rows: List[dict] = None) -> List[dict]:
    league_label = LEAGUES[league_key].label
    stats_rows = []
    existing_by_player = index_existing_stats(existing_rows or [])
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
        stats_row = None
        api_failed = False
        try:
            performances = fetch_performance_games(
                session,
                player['id'],
                timeout,
            )
            stats_row = build_player_stats_from_api(
                player,
                performances,
                league_key,
                season,
                league_label,
            )
        except TransfermarktVerificationError:
            raise
        except (requests.RequestException, RuntimeError) as error:
            api_failed = True
            print(
                f'Warning: API stats refresh failed for {player["name"]}: '
                f'{error}. Falling back to legacy page parser.',
                flush=True,
            )

        if stats_row is None:
            try:
                doc = html.fromstring(fetch_text(session, url, timeout))
                cells = pick_stats_row(doc, league_key)
                position_label = extract_position_label(doc)
                if cells:
                    stats_row = build_player_stats(
                        player,
                        cells,
                        league_label,
                        position_label,
                    )
                elif doc.xpath('//tm-player-performance-table-new'):
                    stats_row = build_player_stats(
                        player,
                        [],
                        league_label,
                        player['position'],
                    )
                    if api_failed and existing_by_player.get(player['id']):
                        stats_row = existing_by_player[player['id']]
                        print(
                            f'Warning: preserving existing stats for '
                            f'{player["name"]} ({player["id"]}) after '
                            f'transient API failure.',
                            flush=True,
                        )
                else:
                    print(
                        f'Warning: no {league_key} competition row found for '
                        f'{player["name"]} ({player["id"]})',
                        flush=True,
                    )
            except TransfermarktVerificationError:
                raise
            except (requests.RequestException, RuntimeError) as error:
                print(f'Warning: failed to refresh stats for {player["name"]}: '
                      f'{error}', flush=True)

        stats_rows.append(
            stats_row or build_player_stats(
                player,
                [],
                league_label,
                player['position'],
            )
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
