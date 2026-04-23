import argparse
import csv
import json
import re
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

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
STAT_VALUE_FIELDS = ['played', 'goals', 'assists',
                     'yellow_cards', 'second_yellows', 'red_cards',
                     'conceded', 'clean_sheets', 'minutes']
TABLE_FIELDS = ['rank', 'club', 'logo', 'played', 'wins', 'draws',
                'losses', 'goals', 'diff', 'points', 'form']

REQUEST_HEADERS = {
    'User-Agent': (
        # A mainstream desktop UA seems to reduce Transfermarkt WAF challenges
        # when paired with a freshly-copied browser cookie.
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8,'
        'application/signed-exchange;v=b3;q=0.7'
    ),
    'Referer': 'https://www.transfermarkt.com/',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-User': '?1',
    'Sec-Fetch-Dest': 'document',
    'Cache-Control': 'max-age=0',
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


CLUB_ALIASES: Dict[str, List[str]] = {
    'afcbournemouth': ['bournemouth'],
    'arsenalfc': ['arsenal'],
    'brightonhovealbion': ['brighton', 'brightonhove'],
    'brentfordfc': ['brentford'],
    'evertonfc': ['everton'],
    'leedsunited': ['leeds'],
    'liverpoolfc': ['liverpool'],
    'manchestercity': ['mancity'],
    'manchesterunited': ['manutd', 'manunited'],
    'newcastleunited': ['newcastle'],
    'nottinghamforest': ['nottmforest', 'nottmforest'],
    'sunderlandafc': ['sunderland'],
    'tottenhamhotspur': ['tottenham'],
    'westhamunited': ['westham'],
    'wolverhamptonwanderers': ['wolves'],
    'fckrasnodar': ['krasnodar', 'krsndr'],
    'fcparinizhniynovgorod': ['pari', 'parinn'],
    'dynamomoscow': ['dynamo'],
    'dinamomakhachkala': ['dinm', 'dinamomakhach', 'dinamomakhachk'],
    'akhmatgrozny': ['akhmat'],
    'fcsochi': ['fksochi', 'sochi'],
    'rubinkazan': ['rubin'],
    'lokomotivmoscow': ['loko', 'lokomoscow'],
    'zenitstpetersburg': ['zenit', 'zenitspb'],
    'baltikakaliningrad': ['balt', 'baltika'],
    'akrontolyatti': ['akron'],
    'krylyasovetovsamara': ['kssamara', 'samara'],
    'atalantabc': ['atalanta'],
    'bolognafc1909': ['bolo', 'bologna'],
    'cagliaricalcio': ['caglia', 'cagliari'],
    'intermilan': ['inter'],
    'juventusfc': ['juve', 'juventus'],
    'sscnapoli': ['napoli'],
    'udinesecalcio': ['udine', 'udinese'],
    'ussassuolo': ['sassuo', 'sassuolo'],
    'hellasverona': ['hellas'],
    'acfiorentina': ['fiorentina'],
    'parmacalcio1913': ['parma'],
    'uscremonese': ['cremonese'],
    'uslecce': ['lecce'],
}

ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in CLUB_ALIASES.items()
    for alias in aliases
}


def canonical_club_identity(value: str) -> str:
    identity = club_identity(value)
    return ALIAS_TO_CANONICAL.get(identity, identity)


def dedupe_team_names(names: List[str]) -> List[str]:
    deduped: List[str] = []
    seen_indices: Dict[str, int] = {}

    for raw_name in names:
        name = normalize_text(raw_name)
        if not name:
            continue
        identity = canonical_club_identity(name)
        if not identity:
            continue
        existing_index = seen_indices.get(identity)
        if existing_index is None:
            seen_indices[identity] = len(deduped)
            deduped.append(name)
            continue

        # Prefer the most descriptive label when the page exposes both a short
        # scoreboard alias and a fuller club name in the same row.
        if len(name) > len(deduped[existing_index]):
            deduped[existing_index] = name

    return deduped


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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict:
    with path.open(encoding='utf-8') as json_file:
        return json.load(json_file)


def slugify_key(value: str) -> str:
    normalized = re.sub(r'[^a-z0-9]+', '-', normalize_text(value).casefold())
    return normalized.strip('-')


def iter_group_matches(payload: Optional[dict]) -> Iterable[Tuple[str, dict]]:
    for group in (payload or {}).get('groups', []):
        group_key = normalize_text(group.get('key', ''))
        for match in group.get('matches', []):
            yield group_key, match


def match_identity(group_key: str, match: dict) -> Tuple[str, str, str, str, str]:
    return (
        normalize_text(group_key),
        normalize_text(match.get('date', '')),
        normalize_text(match.get('time', '')),
        canonical_club_identity(match.get('homeTeam', '')),
        canonical_club_identity(match.get('awayTeam', '')),
    )


def detect_updated_match_clubs(existing_payload: Optional[dict],
                               latest_payload: dict) -> List[str]:
    existing_scores = {
        match_identity(group_key, match): normalize_text(match.get('score', ''))
        for group_key, match in iter_group_matches(existing_payload)
    }
    changed_clubs = []
    seen_clubs = set()

    for group_key, match in iter_group_matches(latest_payload):
        new_score = normalize_text(match.get('score', ''))
        if not new_score:
            continue

        key = match_identity(group_key, match)
        old_score = existing_scores.get(key, '')
        if new_score == old_score:
            continue

        for team_name in (match.get('homeTeam', ''), match.get('awayTeam', '')):
            team_name = normalize_text(team_name)
            team_identity = canonical_club_identity(team_name)
            if not team_name or not team_identity or team_identity in seen_clubs:
                continue
            seen_clubs.add(team_identity)
            changed_clubs.append(team_name)

    return changed_clubs


def name_tokens(value: str) -> List[str]:
    return [
        token for token in re.split(r'[^a-z0-9]+', normalize_text(value).casefold())
        if token
    ]


def names_loosely_match(left: str, right: str) -> bool:
    left_tokens = name_tokens(left)
    right_tokens = name_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    if all(
        any(
            left_token.startswith(right_token)
            or right_token.startswith(left_token)
            for right_token in right_tokens
        )
        for left_token in left_tokens
    ):
        return True

    if all(
        any(
            left_token.startswith(right_token)
            or right_token.startswith(left_token)
            for left_token in left_tokens
        )
        for right_token in right_tokens
    ):
        return True

    return False


def resolve_team_names(changed_names: Iterable[str], teams: List[dict]) -> Tuple[List[dict], List[str]]:
    resolved_teams: List[dict] = []
    unresolved_names: List[str] = []
    seen_team_ids = set()

    for changed_name in changed_names:
        target_identity = canonical_club_identity(changed_name)
        matched_team = None

        for team in teams:
            team_name = team.get('name', '')
            if canonical_club_identity(team_name) == target_identity:
                matched_team = team
                break

        if matched_team is None:
            for team in teams:
                if names_loosely_match(changed_name, team.get('name', '')):
                    matched_team = team
                    break

        if matched_team is None:
            unresolved_names.append(changed_name)
            continue

        team_identity = canonical_club_identity(matched_team.get('name', ''))
        if team_identity in seen_team_ids:
            continue
        seen_team_ids.add(team_identity)
        resolved_teams.append(matched_team)

    return resolved_teams, unresolved_names


def matchday_number_from_key(group_key: str) -> Optional[int]:
    match = re.fullmatch(r'md-(\d+)', normalize_text(group_key))
    if not match:
        return None
    return int(match.group(1))


def domestic_matchdays_to_refresh(existing_payload: Optional[dict],
                                  total_matchdays: int) -> List[int]:
    if total_matchdays <= 0:
        return []

    if not existing_payload:
        return list(range(1, total_matchdays + 1))

    pending_matchdays: List[int] = []
    completed_matchdays: List[int] = []

    for group in existing_payload.get('groups', []):
        matchday = matchday_number_from_key(group.get('key', ''))
        if not matchday:
            continue

        matches = group.get('matches', [])
        if not matches:
            continue

        if any(not normalize_text(match.get('score', '')) for match in matches):
            pending_matchdays.append(matchday)
        else:
            completed_matchdays.append(matchday)

    if pending_matchdays:
        refresh_matchdays = set(pending_matchdays)
        if completed_matchdays:
            refresh_matchdays.add(max(completed_matchdays))
        return [
            matchday for matchday in sorted(refresh_matchdays)
            if 1 <= matchday <= total_matchdays
        ]

    if completed_matchdays:
        return [max(completed_matchdays)]

    return [1]


def normalize_match_group(header: str) -> Tuple[str, str, int]:
    """Return (key, label, order) for a match group header."""
    text = normalize_text(header)
    lowered = text.casefold()

    matchday = re.search(r'(matchday|spieltag)\s*(\d+)', lowered)
    if matchday:
        day = int(matchday.group(2))
        return f'md-{day:02d}', f'Matchday {day}', day

    round_number = re.search(r'(round)\s*(\d+)', lowered)
    if round_number:
        number = int(round_number.group(2))
        return f'round-{number:02d}', f'Round {number}', 100 + number

    key = slugify_key(lowered)
    return f'stage-{key}' if key else 'stage', text or 'Stage', 200


def extract_score(text: str) -> str:
    """Extract a score like 2:1 or 2:1 (4:3) from raw row text."""
    normalized = normalize_text(text)
    # Avoid treating kickoff times like "6:45 PM" as scores.
    lowered = normalized.casefold()
    if re.search(r'\b(am|pm)\b', lowered):
        return ''
    main = re.search(r'(\d+)\s*:\s*(\d+)', normalized)
    if not main:
        return ''
    score = f'{main.group(1)}:{main.group(2)}'
    after = normalized[main.end():]
    pens = re.search(r'\((\d+)\s*:\s*(\d+)\)', after)
    if pens:
        score += f' ({pens.group(1)}:{pens.group(2)})'
    return score


def team_slug_from_link(link: str) -> str:
    """Extract the team slug (first URL path segment) from a Transfermarkt link."""
    normalized = normalize_text(link)
    if not normalized:
        return ''
    try:
        path = urlparse(normalized).path
    except Exception:
        path = normalized
    parts = [part for part in path.split('/') if part]
    return parts[0] if parts else ''


def extract_score_from_row_cells(cells: List[html.HtmlElement],
                                 skip_prefix: int = 2) -> str:
    """Prefer extracting the score from dedicated result cells (not date/time)."""
    if not cells:
        return ''
    for cell in reversed(cells[skip_prefix:]):
        value = normalize_text(' '.join(cell.xpath('.//text()')))
        score = extract_score(value)
        if score:
            return score
    return ''


def is_club_abbreviation(value: str) -> bool:
    """Heuristic filter for 3-4 letter uppercase abbreviations (e.g. LIV)."""
    text = normalize_text(value)
    if not text or ' ' in text:
        return False
    letters = re.sub(r'[^A-Za-z]', '', text)
    if not letters:
        return False
    return len(letters) <= 4 and letters.isupper()


def parse_fixture_table(table: html.HtmlElement) -> List[dict]:
    matches: List[dict] = []
    for row in table.xpath('.//tr[td]'):
        team_links = row.xpath('.//a[contains(@href, "/verein/")]')
        raw_team_names: List[str] = []
        for link in team_links:
            name = normalize_text(' '.join(link.xpath('.//text()')))
            if name:
                raw_team_names.append(name)
        team_names = dedupe_team_names(raw_team_names)
        if len(team_names) < 2:
            continue

        cells = row.xpath('./td')
        date_value = normalize_text(' '.join(cells[0].xpath('.//text()'))) if cells else ''
        time_value = normalize_text(' '.join(cells[1].xpath('.//text()'))) if len(cells) > 1 else ''
        score = extract_score_from_row_cells(cells)

        matches.append({
            'date': date_value,
            'time': time_value,
            'homeTeam': team_names[0],
            'awayTeam': team_names[1],
            'score': score,
        })
    return matches


def parse_spieltag_matches(doc: html.HtmlElement) -> List[dict]:
    """Parse fixture rows from a 'spieltag' page (domestic league matchday)."""
    matches: List[dict] = []
    # Transfermarkt renders each match as a "table-grosse-schrift" row, followed
    # by separate metadata rows (kickoff, referee, attendance, events). We only
    # want the main match rows plus the kickoff metadata.
    for row in doc.xpath(
        '//a[contains(@href, "/spielbericht/index/spielbericht")]'
        '/ancestor::tr[contains(@class, "table-grosse-schrift")][1]'
    ):
        team_links = row.xpath('.//a[contains(@href, "/verein/")]')
        teams: List[str] = []
        for link in team_links:
            name = normalize_text(' '.join(link.xpath('.//text()')))
            if name:
                teams.append(name)

        unique = dedupe_team_names(teams)

        full_names = [name for name in unique if not is_club_abbreviation(name)]
        if len(full_names) >= 2:
            home_name, away_name = full_names[0], full_names[1]
        elif len(unique) >= 2:
            home_name, away_name = unique[0], unique[1]
        else:
            continue

        cells = row.xpath('./td')
        score = extract_score_from_row_cells(cells, skip_prefix=0)

        date_value = ''
        time_value = ''
        meta_row = row.xpath('following-sibling::tr[1]')
        if meta_row:
            meta_text = normalize_text(' '.join(meta_row[0].xpath('.//text()')))
            match = re.search(
                r'([A-Za-z]{3}\s+\d{2}/\d{2}/\d{4})\s*-\s*(\d{1,2}:\d{2}\s*(?:AM|PM))',
                meta_text,
                re.IGNORECASE,
            )
            if match:
                date_value = match.group(1)
                time_value = match.group(2).upper()

        matches.append({
            'date': date_value,
            'time': time_value,
            'homeTeam': home_name,
            'awayTeam': away_name,
            'score': score,
        })

    return matches


def parse_team_schedule_matches(doc: html.HtmlElement, table_title: str,
                                club_name: str) -> List[dict]:
    """Parse matches from a club schedule table (e.g. UEFA Champions League)."""
    matches: List[dict] = []
    tables = doc.xpath(
        f'//h2[contains(normalize-space(.), "{table_title}")]/following::table[1]'
    )
    if not tables:
        return matches
    table = tables[0]

    for row in table.xpath('.//tbody/tr[td]'):
        cells = [
            normalize_text(' '.join(td.xpath('.//text()')))
            for td in row.xpath('./td')
        ]
        if len(cells) < 9:
            continue

        stage = cells[0]
        date_value = cells[1]
        time_value = cells[2]
        venue = cells[3]
        opponent = cells[6] if len(cells) > 6 else ''
        result = cells[-1]

        # Only keep the league phase / group stage fixtures here.
        stage_norm = normalize_text(stage).casefold()
        if stage_norm not in {'group stage', 'league phase', 'league stage'}:
            continue

        home = club_name
        away = opponent
        if venue == 'A':
            home, away = opponent, club_name

        matches.append({
            'date': date_value,
            'time': time_value,
            'homeTeam': home,
            'awayTeam': away,
            'score': extract_score(result),
        })

    return matches


def parse_ddmmyyyy(date_value: str) -> Optional[date]:
    match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_value or '')
    if not match:
        return None
    day, month, year = (int(match.group(1)), int(match.group(2)),
                        int(match.group(3)))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def group_matches_into_matchdays(matches: List[dict]) -> List[dict]:
    """Infer matchdays by clustering Tue/Wed matchweeks into sequential buckets."""
    dated = []
    for match in matches:
        dt = parse_ddmmyyyy(match.get('date', ''))
        if not dt:
            continue
        dated.append((dt, match))

    if not dated:
        return []

    dated.sort(key=lambda item: item[0])
    buckets: List[List[dict]] = []
    current: List[dict] = []
    current_anchor = dated[0][0]

    for dt, match in dated:
        # New matchday when we're more than 3 days away from the first date.
        if (dt - current_anchor).days > 3:
            buckets.append(current)
            current = []
            current_anchor = dt
        current.append(match)

    if current:
        buckets.append(current)

    groups = []
    for index, bucket in enumerate(buckets, start=1):
        groups.append({
            'key': f'md-{index}',
            'label': f'Matchday {index}',
            'order': index,
            'matches': bucket,
        })
    return groups


def fetch_match_groups(session: requests.Session, league_key: str,
                       season: int, timeout: int,
                       bracket: Optional[dict] = None,
                       teams: Optional[List[dict]] = None,
                       club_count: Optional[int] = None,
                       existing_payload: Optional[dict] = None,
                       delay: float = 0.0) -> dict:
    league = LEAGUES[league_key]
    groups: "OrderedDict[str, dict]" = OrderedDict()

    if league.family == 'domestic':
        # Domestic competitions expose a clean matchday URL. Use club_count (from the
        # current table) to infer how many matchdays exist.
        matchdays = None
        if club_count:
            matchdays = max(1, (club_count - 1) * 2)
        if matchdays:
            for group in (existing_payload or {}).get('groups', []):
                group_key = normalize_text(group.get('key', ''))
                order = matchday_number_from_key(group_key)
                if not group_key or order is None:
                    continue
                groups[group_key] = {
                    'key': group_key,
                    'label': group.get('label') or f'Matchday {order}',
                    'order': order,
                    'matches': group.get('matches', []),
                }

            matchdays_to_fetch = domestic_matchdays_to_refresh(
                existing_payload,
                matchdays,
            )
            print(
                f'  refreshing domestic matchdays: '
                f'{", ".join(str(matchday) for matchday in matchdays_to_fetch)}',
                flush=True,
            )
            for matchday in matchdays_to_fetch:
                url = (
                    f'https://www.transfermarkt.com/{league.table_slug}/spieltag/'
                    f'wettbewerb/{league.site_id}/saison_id/{season}/spieltag/{matchday}'
                )
                doc = html.fromstring(fetch_text(session, url, timeout))
                matches = parse_spieltag_matches(doc)
                if not matches:
                    # Stop early if Transfermarkt stops returning fixture rows.
                    break
                key = f'md-{matchday}'
                groups[key] = {
                    'key': key,
                    'label': f'Matchday {matchday}',
                    'order': matchday,
                    'matches': matches,
                }
                if delay:
                    time.sleep(delay)
    else:
        # UEFA competitions: infer league-phase matchdays by scraping each club's
        # schedule and clustering matchweeks.
        league_phase_matches: List[dict] = []
        if teams:
            seen = set()
            for team in teams:
                team_id = team.get('id')
                club_name = team.get('name')
                if not team_id or not club_name:
                    continue
                slug = team.get('slug') or team_slug_from_link(team.get('link', ''))
                if not slug:
                    continue
                url = f'https://www.transfermarkt.com/{slug}/spielplan/verein/{team_id}/saison_id/{season}'
                doc = html.fromstring(fetch_text(session, url, timeout))
                team_matches = parse_team_schedule_matches(doc, league.label, club_name)
                for match in team_matches:
                    sig = (
                        match.get('date', ''),
                        match.get('time', ''),
                        match.get('homeTeam', ''),
                        match.get('awayTeam', ''),
                    )
                    if sig in seen:
                        continue
                    seen.add(sig)
                    league_phase_matches.append(match)
                if delay:
                    time.sleep(delay)

        for group in group_matches_into_matchdays(league_phase_matches):
            groups[group['key']] = group

    # Add explicit knockout matches for UEFA competitions to make playoff
    # browsing easier than fishing them out of the full schedule.
    if bracket and bracket.get('rounds'):
        base_order = 1000
        for round_data in bracket.get('rounds', []):
            round_label = round_data.get('label', 'Playoffs')
            if normalize_text(round_label).casefold() == 'knockout stage':
                continue
            matches_by_leg: "OrderedDict[str, List[dict]]" = OrderedDict()
            for tie in round_data.get('ties', []):
                for match in tie.get('matches', []):
                    leg = match.get('leg') or ''
                    matches_by_leg.setdefault(leg, []).append({
                        'date': match.get('date', ''),
                        'time': match.get('time', ''),
                        'homeTeam': match.get('homeTeam', ''),
                        'awayTeam': match.get('awayTeam', ''),
                        'score': extract_score(match.get('result', '')),
                    })
            for leg, matches in matches_by_leg.items():
                suffix = f' · {leg}' if leg else ''
                key = f'ko-{slugify_key(round_label)}{("-" + slugify_key(leg)) if leg else ""}'
                groups[key] = {
                    'key': key,
                    'label': f'{round_label}{suffix}',
                    'order': base_order,
                    'matches': matches,
                }
                base_order += 1

    ordered = sorted(
        groups.values(),
        key=lambda item: (item.get('order', 9999), item.get('label', '')),
    )
    for item in ordered:
        item.pop('order', None)
    return {'groups': ordered}


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
    league_dir = TMSTATS_DIR / league_key
    league = LEAGUES[league_key]
    league_label = league.label
    players_csv = league_dir / f'{league_key}_players_{season}.csv'
    stats_csv = league_dir / f'{league_key}_stats_{season}.csv'
    bracket_json = league_dir / f'{league_key}_bracket_{season}.json'
    matches_json = league_dir / f'{league_key}_matches_{season}.json'

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

    stats = fetch_stats(
        session,
        league_key,
        players,
        season,
        timeout,
        teams=teams,
        delay=delay,
    )

    existing_stats = read_csv_rows(stats_csv) if stats_csv.exists() else []
    stats_output = pick_stats_output(stats, existing_stats, league_key)

    write_csv(stats_csv, stats_output, STATS_FIELDS)
    write_csv(league_dir / f'{league_key}_table_{season}.csv',
              table, TABLE_FIELDS)
    bracket_payload = None
    if league.supports_bracket:
        try:
            bracket_payload = fetch_knockout_bracket(
                session, league_key, season, timeout
            )
            write_json(bracket_json, bracket_payload)
        except Exception as error:
            print(f'Warning: failed to refresh knockout bracket for {league_key}: '
                  f'{error}', flush=True)
            bracket_payload = None

    try:
        write_json(
            matches_json,
            fetch_match_groups(
                session,
                league_key,
                season,
                timeout,
                bracket=bracket_payload,
                teams=teams,
                club_count=len(table),
                delay=delay,
            ),
        )
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: '
              f'{error}', flush=True)
    render_pdf(league_dir / f'{league_key}_stats_{season}.pdf',
               'stats', league_label, season, stats_output)
    render_pdf(league_dir / f'{league_key}_table_{season}.pdf',
               'table', league_label, season, table)

    return {
        'league': league_key,
        'season': season,
        'clubs': len(teams),
        'players': len(players),
        'stats_rows': len(stats_output),
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


def refresh_changed_team_stats_only(
        league_key: str, season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> dict:
    """Refresh table/matches, then update stats only for clubs in changed matches."""
    season = season or current_season_start_year()
    league_dir = TMSTATS_DIR / league_key
    league = LEAGUES[league_key]
    league_label = league.label
    players_csv = league_dir / f'{league_key}_players_{season}.csv'
    stats_csv = league_dir / f'{league_key}_stats_{season}.csv'
    table_csv = league_dir / f'{league_key}_table_{season}.csv'
    bracket_json = league_dir / f'{league_key}_bracket_{season}.json'
    matches_json = league_dir / f'{league_key}_matches_{season}.json'
    table_pdf = league_dir / f'{league_key}_table_{season}.pdf'
    stats_pdf = league_dir / f'{league_key}_stats_{season}.pdf'

    if not (players_csv.exists() and stats_csv.exists() and matches_json.exists()):
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

    existing_matches = read_json(matches_json)
    existing_players = load_existing_players(players_csv)
    existing_stats = read_csv_rows(stats_csv)

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

    bracket_payload = None
    if league.supports_bracket:
        try:
            bracket_payload = fetch_knockout_bracket(
                session, league_key, season, timeout
            )
            write_json(bracket_json, bracket_payload)
        except Exception as error:
            print(f'Warning: failed to refresh knockout bracket for {league_key}: '
                  f'{error}', flush=True)
            bracket_payload = None

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

    write_json(matches_json, latest_matches)
    write_csv(table_csv, table, TABLE_FIELDS)
    render_pdf(table_pdf, 'table', league_label, season, table)

    if not changed_clubs:
        print('  no newly completed or changed matches; player stats unchanged',
              flush=True)
        return {
            'league': league_key,
            'season': season,
            'clubs': len(teams),
            'players': len(existing_players),
            'stats_rows': len(existing_stats),
            'table_rows': len(table),
        }

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
        return {
            'league': league_key,
            'season': season,
            'clubs': len(teams),
            'players': len(existing_players),
            'stats_rows': len(existing_stats),
            'table_rows': len(table),
        }

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
    write_csv(players_csv, players_output, PLAYER_FIELDS)

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
    write_csv(stats_csv, stats_output, STATS_FIELDS)
    render_pdf(stats_pdf, 'stats', league_label, season, stats_output)

    return {
        'league': league_key,
        'season': season,
        'clubs': len(teams),
        'players': len(players_output),
        'stats_rows': len(stats_output),
        'table_rows': len(table),
    }


def refresh_matches_only(league_key: str, season: int = None,
                         timeout: int = DEFAULT_TIMEOUT,
                         delay: float = DEFAULT_DELAY) -> dict:
    """Refresh only match/bracket JSON snapshots (no roster or player stats)."""
    season = season or current_season_start_year()
    session = build_session()
    league_dir = TMSTATS_DIR / league_key
    matches_json = league_dir / f'{league_key}_matches_{season}.json'
    existing_matches = read_json(matches_json) if matches_json.exists() else None

    teams, table = fetch_current_table(session, league_key, season, timeout)

    bracket_payload = None
    if LEAGUES[league_key].supports_bracket:
        try:
            bracket_payload = fetch_knockout_bracket(session, league_key, season, timeout)
            write_json(league_dir / f'{league_key}_bracket_{season}.json', bracket_payload)
        except Exception as error:
            print(f'Warning: failed to refresh knockout bracket for {league_key}: {error}', flush=True)
            bracket_payload = None

    try:
        write_json(
            matches_json,
            fetch_match_groups(
                session,
                league_key,
                season,
                timeout,
                bracket=bracket_payload,
                teams=teams,
                club_count=len(table),
                existing_payload=existing_matches,
                delay=delay,
            ),
        )
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: {error}', flush=True)

    return {
        'league': league_key,
        'season': season,
        'clubs': len(table),
        'players': 0,
        'stats_rows': 0,
        'table_rows': len(table),
    }


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
