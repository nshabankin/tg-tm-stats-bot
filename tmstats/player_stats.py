import re
import time
from pathlib import Path
from typing import Iterable, List

import requests
from lxml import html

from .catalog import LEAGUES
from .identity import canonical_club_identity, normalize_text
from .source import fetch_json, fetch_text
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
    'la_liga': {'laliga'},
    'serie_a': {'seriea'},
    'bundesliga': {'bundesliga'},
    'ligue_1': {'ligue1'},
    'rpl': {'premierliga', 'russianpremierleague'},
    'ucl': {'championsleague'},
    'uel': {'europaleague'},
    'uecl': {'conferenceleague', 'uefaconferenceleague'},
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
                  timeout: int, delay: float = 0.25) -> List[dict]:
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
                delay: float = 0.25) -> List[dict]:
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
