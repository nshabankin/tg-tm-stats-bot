import argparse
import csv
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from lxml import html

from .pdf_export import render_pdf


BASE_DIR = Path(__file__).resolve().parent.parent
TMSTATS_DIR = BASE_DIR / 'tmstats'
load_dotenv(BASE_DIR / '.env')

DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25
MAX_RETRIES = 3
RETRY_STATUSES = {405, 429, 500, 502, 503, 504}

TEAM_FIELDS = ['id', 'name', 'link',
               'rank', 'played', 'wins', 'draws',
               'losses', 'goals', 'diff', 'points']
PLAYER_FIELDS = ['id', 'name', 'shirtNumber', 'positionId',
                 'position', 'club', 'link']
STATS_FIELDS = ['player_name', 'number', 'position',
                'club', 'league',
                'played', 'goals', 'assists',
                'yellow_cards', 'second_yellows', 'red_cards',
                'conceded', 'clean_sheets',
                'minutes']
TABLE_FIELDS = ['rank', 'club', 'played', 'wins', 'draws',
                'losses', 'goals', 'diff', 'points']

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

LEAGUES: Dict[str, Dict[str, str]] = {
    'epl': {
        'site_id': 'GB1',
        'table_slug': 'premier-league',
        'label': 'Premier League',
    },
    'serie_a': {
        'site_id': 'IT1',
        'table_slug': 'serie-a',
        'label': 'Serie A',
    },
    'la_liga': {
        'site_id': 'ES1',
        'table_slug': 'laliga',
        'label': 'La Liga',
    },
    'bundesliga': {
        'site_id': 'L1',
        'table_slug': 'bundesliga',
        'label': 'Bundesliga',
    },
    'ligue_1': {
        'site_id': 'FR1',
        'table_slug': 'ligue-1',
        'label': 'Ligue 1',
    },
    'rpl': {
        'site_id': 'RU1',
        'table_slug': 'premier-liga',
        'label': 'Russian Premier League',
    },
}


def current_season_start_year(today: date = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    cookie = os.getenv('TM_COOKIE')
    if cookie:
        session.headers['Cookie'] = cookie.strip()
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


def build_team_link(href: str) -> str:
    match = re.search(r'/([^/]+)/[^/]+/verein/(\d+)', href)
    if not match:
        return normalize_text(href)
    slug, team_id = match.groups()
    return f'/{slug}/startseite/verein/{team_id}'


def write_csv(path: Path, rows: Iterable[dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline='', encoding='utf-8') as csv_file:
        return list(csv.DictReader(csv_file))


def fetch_current_table(session: requests.Session, league_key: str,
                        season: int, timeout: int) -> Tuple[List[dict], List[dict]]:
    league = LEAGUES[league_key]
    url = (
        f'https://www.transfermarkt.com/{league["table_slug"]}/'
        f'tabelle/wettbewerb/{league["site_id"]}/saison_id/{season}'
    )
    doc = html.fromstring(fetch_text(session, url, timeout))
    rows = doc.xpath('//table[contains(@class, "items")]/tbody/tr')

    teams = []
    table_rows = []

    for row in rows:
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
            'rank': values[0],
            'played': values[3],
            'wins': values[4],
            'draws': values[5],
            'losses': values[6],
            'goals': values[7],
            'diff': values[8],
            'points': values[9] if len(values) > 9 else '',
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


def extract_stats_cells(doc: html.HtmlElement) -> List[str]:
    row = doc.xpath('//*[@id="yw1"]/table/tbody/tr[1]/td')
    return [normalize_text(' '.join(cell.xpath('.//text()'))) for cell in row]


def build_player_stats(player: dict, cells: List[str], league_label: str,
                       position_label: str) -> dict:
    number = f'#{player["shirtNumber"]}' if player['shirtNumber'] else ''
    stats = {
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
                delay: float = DEFAULT_DELAY) -> List[dict]:
    league_label = LEAGUES[league_key]['label']
    stats_rows = []

    for index, player in enumerate(players, start=1):
        slug = player['link'].split('/')[1]
        url = (
            f'https://www.transfermarkt.com/{slug}/leistungsdaten/'
            f'spieler/{player["id"]}/plus/0?saison={season}'
        )
        try:
            doc = html.fromstring(fetch_text(session, url, timeout))
            cells = extract_stats_cells(doc)
            position_label = extract_position_label(doc)
        except requests.RequestException as error:
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
                   delay: float = DEFAULT_DELAY) -> dict:
    season = season or current_season_start_year()
    session = build_session()
    league_dir = TMSTATS_DIR / league_key
    league_label = LEAGUES[league_key]['label']

    print(f'Refreshing {league_key} for season {season}', flush=True)

    teams, table = fetch_current_table(session, league_key, season, timeout)
    players = fetch_players(session, teams, timeout, delay)
    print(f'  fetched {len(teams)} teams and {len(players)} players',
          flush=True)
    stats = fetch_stats(session, league_key, players, season, timeout, delay)

    write_csv(league_dir / f'{league_key}_teams_{season}.csv',
              teams, TEAM_FIELDS)
    write_csv(league_dir / f'{league_key}_players_{season}.csv',
              players, PLAYER_FIELDS)
    write_csv(league_dir / f'{league_key}_stats_{season}.csv',
              stats, STATS_FIELDS)
    write_csv(league_dir / f'{league_key}_table_{season}.csv',
              table, TABLE_FIELDS)
    render_pdf(league_dir / f'{league_key}_teams_{season}.pdf',
               'teams', league_label, season, teams)
    render_pdf(league_dir / f'{league_key}_stats_{season}.pdf',
               'stats', league_label, season, stats)
    render_pdf(league_dir / f'{league_key}_table_{season}.pdf',
               'table', league_label, season, table)

    return {
        'league': league_key,
        'season': season,
        'teams': len(teams),
        'players': len(players),
        'stats_rows': len(stats),
        'table_rows': len(table),
    }


def render_league_pdfs(league_key: str, season: int = None) -> dict:
    season = season or current_season_start_year()
    league_dir = TMSTATS_DIR / league_key
    league_label = LEAGUES[league_key]['label']

    table_csv = league_dir / f'{league_key}_table_{season}.csv'
    teams_csv = league_dir / f'{league_key}_teams_{season}.csv'
    stats_csv = league_dir / f'{league_key}_stats_{season}.csv'

    missing = [path.name for path in (table_csv, teams_csv, stats_csv)
               if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f'Missing CSV snapshots for {league_key} season {season}: '
            f'{", ".join(missing)}'
        )

    table_rows = read_csv_rows(table_csv)
    team_rows = read_csv_rows(teams_csv)
    stats_rows = read_csv_rows(stats_csv)

    render_pdf(league_dir / f'{league_key}_table_{season}.pdf',
               'table', league_label, season, table_rows)
    render_pdf(league_dir / f'{league_key}_teams_{season}.pdf',
               'teams', league_label, season, team_rows)
    render_pdf(league_dir / f'{league_key}_stats_{season}.pdf',
               'stats', league_label, season, stats_rows)

    return {
        'league': league_key,
        'season': season,
        'teams': len(team_rows),
        'players': len(stats_rows),
        'stats_rows': len(stats_rows),
        'table_rows': len(table_rows),
    }


def refresh_leagues(league_keys: Iterable[str], season: int = None,
                    timeout: int = DEFAULT_TIMEOUT,
                    delay: float = DEFAULT_DELAY) -> List[dict]:
    results = []
    for league_key in league_keys:
        results.append(refresh_league(league_key, season, timeout, delay))
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
        choices=sorted(LEAGUES.keys()),
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    league_keys = args.league or []

    if args.all or not league_keys:
        league_keys = list(LEAGUES.keys())

    if args.pdf_only:
        results = render_pdfs_for_leagues(league_keys, season=args.season)
        completion_label = 'PDF render complete'
    else:
        results = refresh_leagues(league_keys,
                                  season=args.season,
                                  timeout=args.timeout,
                                  delay=args.delay)
        completion_label = 'Refresh complete'

    print()
    print(completion_label)
    for result in results:
        print(
            f'- {result["league"]}: '
            f'{result["teams"]} teams, '
            f'{result["players"]} players, '
            f'{result["stats_rows"]} stats rows, '
            f'{result["table_rows"]} table rows'
        )


if __name__ == '__main__':
    main()
