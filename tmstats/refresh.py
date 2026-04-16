import argparse
import csv
import json
import re
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from lxml import html

from config import TMSTATS_DIR, get_env
from .catalog import LEAGUES, LEAGUE_KEYS
from .pdf_export import render_pdf

DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25
MAX_RETRIES = 3
RETRY_STATUSES = {405, 429, 500, 502, 503, 504}

PLAYER_FIELDS = ['id', 'name', 'shirtNumber', 'positionId',
                 'position', 'club', 'link']
STATS_FIELDS = ['player_id', 'player_name', 'number', 'position',
                'club', 'league',
                'played', 'goals', 'assists',
                'yellow_cards', 'second_yellows', 'red_cards',
                'conceded', 'clean_sheets',
                'minutes']
TABLE_FIELDS = ['rank', 'club', 'logo', 'played', 'wins', 'draws',
                'losses', 'goals', 'diff', 'points', 'form']

REQUEST_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) '
        'Gecko/20100101 Firefox/128.0'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.transfermarkt.com/',
}

POSITION_LABELS = {
    1: 'Goalkeeper',
    2: 'Defender',
    3: 'Midfield',
    4: 'Forward',
}

KNOCKOUT_STAGE_ORDER = {
    'playoffs': 1,
    'round_of_16': 2,
    'quarter_finals': 3,
    'semi_finals': 4,
    'final': 5,
}

KNOCKOUT_STAGE_LABELS = {
    'intermediate stage': ('playoffs', 'Knockout Play-offs'),
    'last 16': ('round_of_16', 'Round of 16'),
    'quarter-finals': ('quarter_finals', 'Quarter-finals'),
    'semi-finals': ('semi_finals', 'Semi-finals'),
    'final': ('final', 'Final'),
}


def current_season_start_year(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def competition_path(league_key: str, page: str, season: int) -> str:
    league = LEAGUES[league_key]
    if league.tm_scope == 'pokalwettbewerb':
        if page == 'startseite':
            return (
                f'https://www.transfermarkt.com/{league.table_slug}/{page}/'
                f'{league.tm_scope}/{league.site_id}?saison_id={season}'
            )
        return (
            f'https://www.transfermarkt.com/{league.table_slug}/{page}/'
            f'{league.tm_scope}/{league.site_id}/saison_id/{season}'
        )

    return (
        f'https://www.transfermarkt.com/{league.table_slug}/{page}/'
        f'{league.tm_scope}/{league.site_id}/saison_id/{season}'
    )


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    cookie = get_env('TM_COOKIE')
    if cookie:
        session.headers['Cookie'] = cookie
    return session


def request_with_retries(session: requests.Session, url: str,
                         timeout: int) -> requests.Response:
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=timeout)
            if response.headers.get('x-amzn-waf-action') == 'captcha':
                raise RuntimeError(
                    'Transfermarkt requested human verification. '
                    'If this keeps happening, open Transfermarkt in a browser '
                    'and copy your browser cookie string into TM_COOKIE in '
                    '.env before rerunning the refresh.'
                )
            if response.status_code not in RETRY_STATUSES:
                response.raise_for_status()
                return response

            last_error = requests.HTTPError(
                f'{response.status_code} error for {url}',
                response=response,
            )
        except requests.RequestException as error:
            last_error = error

        if attempt < MAX_RETRIES:
            time.sleep(attempt)

    raise last_error


def fetch_json(session: requests.Session, url: str, timeout: int) -> List[dict]:
    response = request_with_retries(session, url, timeout)
    return response.json()


def fetch_text(session: requests.Session, url: str, timeout: int) -> str:
    response = request_with_retries(session, url, timeout)
    return response.text


def normalize_text(value) -> str:
    if value is None:
        return ''
    return ' '.join(str(value).replace('\xa0', ' ').split())


def club_identity(value: str) -> str:
    normalized = normalize_text(value).lower()
    return re.sub(r'[^a-z0-9]+', '', normalized)


def build_team_link(href: str) -> str:
    match = re.search(r'/([^/]+)/[^/]+/verein/(\d+)', href)
    if not match:
        return normalize_text(href)
    slug, team_id = match.groups()
    return f'/{slug}/startseite/verein/{team_id}'


def normalize_asset_url(url: str) -> str:
    normalized = normalize_text(url)
    if not normalized:
        return ''
    if normalized.startswith('//'):
        normalized = f'https:{normalized}'
    if normalized.startswith('/'):
        normalized = f'https://www.transfermarkt.com{normalized}'
    # Standings pages usually expose only the low-res tiny badge. Club pages
    # use the same asset path with the sharper head variant, which reads much
    # better inside the Mini App.
    normalized = normalized.replace('/images/wappen/tiny/', '/images/wappen/head/')
    return normalized


def extract_logo_url(row: html.HtmlElement) -> str:
    candidates = row.xpath(
        './/img[contains(@class, "wappen")]/@data-src'
        ' | .//img[contains(@class, "wappen")]/@src'
        ' | .//img[contains(@class, "wappen")]/@data-srcset'
        ' | .//img[contains(@class, "wappen")]/@srcset'
        ' | .//img/@data-src'
        ' | .//img/@src'
        ' | .//img/@data-srcset'
        ' | .//img/@srcset'
    )
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if not normalized:
            continue
        if ' ' in normalized and ',' in normalized:
            normalized = normalized.split(',')[0].strip().split(' ')[0]
        elif ' ' in normalized:
            normalized = normalized.split(' ')[0]
        return normalize_asset_url(normalized)
    return ''


def write_csv(path: Path, rows: Iterable[dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2)


def read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline='', encoding='utf-8') as csv_file:
        return list(csv.DictReader(csv_file))


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


def parse_domestic_table(doc: html.HtmlElement) -> Tuple[List[dict], List[dict]]:
    rows = doc.xpath('//table[contains(@class, "items")]/tbody/tr')

    teams = []
    table_rows = []

    for rank_index, row in enumerate(rows, start=1):
        href = normalize_text(''.join(row.xpath('.//td[3]//a/@href')))
        title = normalize_text(''.join(row.xpath('.//td[3]//a/@title')))
        display_name = normalize_text(''.join(row.xpath('.//td[3]//a//text()')))
        values = [
            normalize_text(' '.join(cell.xpath('.//text()')))
            for cell in row.xpath('./td')
        ]

        if len(values) < 9 or not href:
            continue

        team_id_match = re.search(r'/verein/(\d+)', href)
        if not team_id_match:
            continue

        team_stats = {
            # Trust the table row order from Transfermarkt and normalize the
            # exported rank to a strict 1..N sequence for downstream consumers.
            'rank': str(rank_index),
            'logo': extract_logo_url(row),
            'played': values[3],
            'wins': values[4],
            'draws': values[5],
            'losses': values[6],
            'goals': values[7],
            'diff': values[8],
            'points': values[9] if len(values) > 9 else '',
            'form': '',
        }
        team_name = title or display_name
        team_link = build_team_link(href)
        team_id = team_id_match.group(1)

        teams.append({
            'id': team_id,
            'name': team_name,
            'link': team_link,
            **team_stats,
        })
        table_rows.append({
            'club': team_name,
            **team_stats,
        })

    return teams, table_rows


def parse_uefa_table(doc: html.HtmlElement) -> Tuple[List[dict], List[dict]]:
    table = doc.xpath(
        '//h2[contains(normalize-space(.), "Group GP")]'
        '/following-sibling::div[contains(@class, "grid-view")][1]'
        '//table[.//th[contains(normalize-space(.), "Pts")]'
        ' and .//th[contains(normalize-space(.), "Goals")]]'
    )
    if not table:
        table = doc.xpath(
            '//table[.//th[contains(normalize-space(.), "Pts")]'
            ' and .//th[contains(normalize-space(.), "Goals")]]'
        )
    if not table:
        return [], []

    teams = []
    table_rows = []

    for row in table[0].xpath('.//tbody/tr[td]'):
        cells = row.xpath('./td')
        if len(cells) < 7:
            continue

        href = normalize_text(''.join(row.xpath('.//a[contains(@href, "/verein/")]/@href')))
        team_id_match = re.search(r'/verein/(\d+)', href)
        if not team_id_match:
            continue

        team_name = normalize_text(' '.join(cells[2].xpath('.//text()')))
        team_stats = {
            'rank': normalize_text(' '.join(cells[0].xpath('.//text()'))),
            'logo': extract_logo_url(row),
            'played': normalize_text(' '.join(cells[3].xpath('.//text()'))),
            'wins': '',
            'draws': '',
            'losses': '',
            'goals': normalize_text(' '.join(cells[5].xpath('.//text()'))),
            'diff': normalize_text(' '.join(cells[4].xpath('.//text()'))),
            'points': normalize_text(' '.join(cells[6].xpath('.//text()'))),
            'form': '',
        }
        team_link = build_team_link(href)
        team_id = team_id_match.group(1)

        teams.append({
            'id': team_id,
            'name': team_name,
            'link': team_link,
            **team_stats,
        })
        table_rows.append({
            'club': team_name,
            **team_stats,
        })

    return teams, table_rows


def fetch_current_table(session: requests.Session, league_key: str,
                        season: int, timeout: int) -> Tuple[List[dict], List[dict]]:
    league = LEAGUES[league_key]
    page = 'tabelle' if league.family == 'domestic' else 'gesamtspielplan'
    doc = html.fromstring(fetch_text(session, competition_path(league_key, page, season), timeout))

    if league.family == 'uefa':
        return parse_uefa_table(doc)

    return parse_domestic_table(doc)


def extract_form_value(row: html.HtmlElement) -> str:
    form_text = normalize_text(' '.join(row.xpath('./td[last()]//text()')))
    return ''.join(character for character in form_text if character in 'WDL')


def fetch_recent_form(session: requests.Session, league_key: str,
                      season: int, timeout: int) -> Dict[str, str]:
    if LEAGUES[league_key].family != 'domestic':
        return {}

    league = LEAGUES[league_key]
    doc = html.fromstring(fetch_text(
        session,
        competition_path(league_key, 'formtabelle', season),
        timeout,
    ))
    rows = doc.xpath(
        '//th[contains(normalize-space(.), "Form")]'
        '/ancestor::table[1]/tbody/tr'
    )
    recent_form = {}

    for row in rows:
        hrefs = row.xpath('.//a[contains(@href, "/verein/")]/@href')
        team_id = None
        for href in hrefs:
            team_id_match = re.search(r'/verein/(\d+)', href)
            if team_id_match:
                team_id = team_id_match.group(1)
                break

        if not team_id:
            continue

        recent_form[team_id] = extract_form_value(row)

    return recent_form


def fetch_players(session: requests.Session, teams: List[dict],
                  timeout: int, delay: float = DEFAULT_DELAY) -> List[dict]:
    players = []

    for team in teams:
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


def normalize_stage_label(label: str) -> Tuple[Optional[str], str, str, int]:
    normalized = normalize_text(label).casefold()
    for prefix, (stage_key, stage_label) in KNOCKOUT_STAGE_LABELS.items():
        if normalized.startswith(prefix):
            leg_label = ''
            if '1st leg' in normalized:
                leg_label = '1st leg'
            elif '2nd leg' in normalized:
                leg_label = '2nd leg'
            elif 'final' in normalized:
                leg_label = 'Final'
            return (
                stage_key,
                stage_label,
                leg_label,
                KNOCKOUT_STAGE_ORDER[stage_key],
            )
    return None, normalize_text(label), '', 999


def knockout_match_label(index: int) -> str:
    return f'Match {index}'


def fetch_knockout_bracket(session: requests.Session, league_key: str,
                           season: int, timeout: int) -> dict:
    league = LEAGUES[league_key]
    if not league.supports_bracket:
        return {'rounds': []}

    doc = html.fromstring(fetch_text(
        session,
        competition_path(league_key, 'gesamtspielplan', season),
        timeout,
    ))
    table = doc.xpath(
        '//h2[contains(normalize-space(.), "Knockout stage")]'
        '/following-sibling::table[1]'
    )
    if not table:
        return {'rounds': []}

    rounds: "OrderedDict[str, dict]" = OrderedDict()
    current_round = None
    current_leg = ''

    for row in table[0].xpath('.//tr'):
        row_class = normalize_text(row.get('class', ''))
        cells = row.xpath('./td')
        if not cells:
            continue

        if 'bg_sturm' in row_class.casefold():
            stage_key, stage_label, leg_label, order = normalize_stage_label(
                normalize_text(' '.join(row.xpath('.//text()')))
            )
            if not stage_key:
                current_round = None
                current_leg = ''
                continue

            current_round = rounds.setdefault(
                stage_key,
                {
                    'key': stage_key,
                    'label': stage_label,
                    'order': order,
                    'ties_by_code': OrderedDict(),
                },
            )
            current_leg = leg_label
            continue

        if len(cells) < 8 or current_round is None:
            continue

        values = [
            normalize_text(' '.join(cell.xpath('.//text()')))
            for cell in cells
        ]
        if not values[3] or not values[7]:
            continue

        tie_code = values[2] or knockout_match_label(
            len(current_round['ties_by_code']) + 1
        )
        tie = current_round['ties_by_code'].setdefault(
            tie_code,
            {
                'code': tie_code,
                'matches': [],
            },
        )
        tie['matches'].append({
            'leg': current_leg,
            'date': values[0],
            'time': values[1],
            'homeTeam': values[3],
            'result': values[5],
            'awayTeam': values[7],
        })

    serialized_rounds = []
    for round_data in rounds.values():
        serialized_rounds.append({
            'key': round_data['key'],
            'label': round_data['label'],
            'order': round_data['order'],
            'ties': list(round_data['ties_by_code'].values()),
        })

    return {
        'rounds': serialized_rounds,
    }


def fetch_stats(session: requests.Session, league_key: str, players: List[dict],
                season: int, timeout: int,
                delay: float = DEFAULT_DELAY) -> List[dict]:
    league_label = LEAGUES[league_key].label
    stats_rows = []

    for index, player in enumerate(players, start=1):
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

        if index % 50 == 0 or index == len(players):
            print(f'  processed {index}/{len(players)} player pages',
                  flush=True)

        if delay:
            time.sleep(delay)

    return stats_rows


def refresh_league(league_key: str, season: int = None,
                   timeout: int = DEFAULT_TIMEOUT,
                   delay: float = DEFAULT_DELAY,
                   refresh_rosters: bool = False) -> dict:
    season = season or current_season_start_year()
    session = build_session()
    league_dir = TMSTATS_DIR / league_key
    league = LEAGUES[league_key]
    league_label = league.label
    players_csv = league_dir / f'{league_key}_players_{season}.csv'
    bracket_json = league_dir / f'{league_key}_bracket_{season}.json'

    print(f'Refreshing {league_key} for season {season}', flush=True)

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

    players = []
    if not refresh_rosters:
        players = load_existing_players(players_csv)
        if players:
            print(f'  reusing {len(players)} players from saved roster',
                  flush=True)

    if not players:
        players = fetch_players(session, teams, timeout, delay)
        write_csv(players_csv, players, PLAYER_FIELDS)
        print(f'  fetched {len(teams)} teams and {len(players)} players',
              flush=True)

    stats = fetch_stats(session, league_key, players, season, timeout, delay)

    write_csv(league_dir / f'{league_key}_stats_{season}.csv',
              stats, STATS_FIELDS)
    write_csv(league_dir / f'{league_key}_table_{season}.csv',
              table, TABLE_FIELDS)
    if league.supports_bracket:
        try:
            write_json(
                bracket_json,
                fetch_knockout_bracket(session, league_key, season, timeout),
            )
        except Exception as error:
            print(f'Warning: failed to refresh knockout bracket for {league_key}: '
                  f'{error}', flush=True)
    render_pdf(league_dir / f'{league_key}_stats_{season}.pdf',
               'stats', league_label, season, stats)
    render_pdf(league_dir / f'{league_key}_table_{season}.pdf',
               'table', league_label, season, table)

    return {
        'league': league_key,
        'season': season,
        'clubs': len(teams),
        'players': len(players),
        'stats_rows': len(stats),
        'table_rows': len(table),
    }


def render_league_pdfs(league_key: str, season: int = None) -> dict:
    season = season or current_season_start_year()
    league_dir = TMSTATS_DIR / league_key
    league_label = LEAGUES[league_key].label

    table_csv = league_dir / f'{league_key}_table_{season}.csv'
    stats_csv = league_dir / f'{league_key}_stats_{season}.csv'

    missing = [path.name for path in (table_csv, stats_csv)
               if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f'Missing CSV snapshots for {league_key} season {season}: '
            f'{", ".join(missing)}'
        )

    table_rows = read_csv_rows(table_csv)
    stats_rows = read_csv_rows(stats_csv)

    render_pdf(league_dir / f'{league_key}_table_{season}.pdf',
               'table', league_label, season, table_rows)
    render_pdf(league_dir / f'{league_key}_stats_{season}.pdf',
               'stats', league_label, season, stats_rows)

    return {
        'league': league_key,
        'season': season,
        'clubs': len(table_rows),
        'players': len(stats_rows),
        'stats_rows': len(stats_rows),
        'table_rows': len(table_rows),
    }


def refresh_leagues(league_keys: Iterable[str], season: int = None,
                    timeout: int = DEFAULT_TIMEOUT,
                    delay: float = DEFAULT_DELAY,
                    refresh_rosters: bool = False) -> List[dict]:
    results = []
    for league_key in league_keys:
        results.append(refresh_league(league_key, season, timeout, delay,
                                      refresh_rosters))
    return results


def refresh_logos_only(league_key: str, season: int = None,
                       timeout: int = DEFAULT_TIMEOUT) -> dict:
    season = season or current_season_start_year()
    table_csv = TMSTATS_DIR / league_key / f'{league_key}_table_{season}.csv'
    if not table_csv.exists():
        raise FileNotFoundError(
            f'Missing table snapshot for {league_key} season {season}: '
            f'{table_csv.name}'
        )

    session = build_session()
    _, latest_table = fetch_current_table(session, league_key, season, timeout)
    latest_by_club = {club_identity(row['club']): row for row in latest_table}
    latest_by_rank = {row['rank']: row for row in latest_table}
    current_rows = read_csv_rows(table_csv)

    updated_rows = []
    for row in current_rows:
        latest = latest_by_club.get(club_identity(row.get('club', '')))
        if not latest:
            latest = latest_by_rank.get(row.get('rank', ''))
        updated_rows.append({
            **row,
            'logo': latest.get('logo', '') if latest else row.get('logo', ''),
        })

    write_csv(table_csv, updated_rows, TABLE_FIELDS)
    render_pdf(
        TMSTATS_DIR / league_key / f'{league_key}_table_{season}.pdf',
        'table',
        LEAGUES[league_key].label,
        season,
        updated_rows,
    )

    return {
        'league': league_key,
        'season': season,
        'clubs': len(updated_rows),
        'players': 0,
        'stats_rows': 0,
        'table_rows': len(updated_rows),
    }


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
    elif args.pdf_only:
        results = render_pdfs_for_leagues(league_keys, season=args.season)
        completion_label = 'PDF render complete'
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
