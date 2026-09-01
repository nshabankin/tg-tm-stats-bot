import re
import time
from collections import OrderedDict
from datetime import date
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from lxml import html

from config import get_env

from .catalog import LEAGUES
from .identity import dedupe_team_names, normalize_text
from .incremental import domestic_matchdays_to_refresh, matchday_number_from_key

MAX_RETRIES = 3
RETRY_STATUSES = {405, 429, 500, 502, 503, 504}

REQUEST_HEADERS = {
    'User-Agent': (
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

KNOCKOUT_STAGE_ORDER = {
    'round_of_32': 1,
    'playoffs': 1,
    'round_of_16': 2,
    'quarter_finals': 3,
    'semi_finals': 4,
    'third_place': 5,
    'final': 6,
}

KNOCKOUT_STAGE_LABELS = {
    'round of 32': ('round_of_32', 'Round of 32'),
    'last 32': ('round_of_32', 'Round of 32'),
    'intermediate stage': ('playoffs', 'Knockout Play-offs'),
    'last 16': ('round_of_16', 'Round of 16'),
    'round of 16': ('round_of_16', 'Round of 16'),
    'quarter-finals': ('quarter_finals', 'Quarter-finals'),
    'quarter finals': ('quarter_finals', 'Quarter-finals'),
    'semi-finals': ('semi_finals', 'Semi-finals'),
    'semi finals': ('semi_finals', 'Semi-finals'),
    'third-place': ('third_place', 'Third-place match'),
    'third place': ('third_place', 'Third-place match'),
    'final': ('final', 'Final'),
}


class TransfermarktVerificationError(RuntimeError):
    """Raised when Transfermarkt serves a site-wide verification challenge."""


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
            verification_page = (
                response.status_code == 202
                or response.headers.get('x-amzn-waf-action') == 'captcha'
                or 'JavaScript is disabled' in response.text
            )
            if verification_page:
                raise TransfermarktVerificationError(
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
    normalized = normalized.replace('/images/wappen/tiny/', '/images/wappen/head/')
    normalized = normalized.replace('/images/flagge/tiny/', '/images/flagge/head/')
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


def extract_score(text: str) -> str:
    normalized = normalize_text(text)
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
    if not cells:
        return ''
    for cell in reversed(cells[skip_prefix:]):
        value = normalize_text(' '.join(cell.xpath('.//text()')))
        score = extract_score(value)
        if score:
            return score
    return ''


def is_club_abbreviation(value: str) -> bool:
    text = normalize_text(value)
    if not text or ' ' in text:
        return False
    letters = re.sub(r'[^A-Za-z]', '', text)
    if not letters:
        return False
    return len(letters) <= 4 and letters.isupper()


def parse_spieltag_matches(doc: html.HtmlElement) -> List[dict]:
    matches: List[dict] = []
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


def first_match_date(values: List[str]) -> str:
    for value in values:
        match = re.search(r'\d{1,2}/\d{1,2}/\d{4}', value or '')
        if match:
            return match.group(0)
    return ''


def first_match_time(values: List[str]) -> str:
    for value in values:
        normalized = normalize_text(value)
        match = re.search(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b', normalized,
                          re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return ''


def parse_tournament_schedule_table(table: html.HtmlElement) -> List[dict]:
    matches: List[dict] = []
    last_date = ''
    last_time = ''
    for row in table.xpath('.//tbody/tr[td] | .//tr[td]'):
        cells = row.xpath('./td')
        values = [
            normalize_text(' '.join(cell.xpath('.//text()')))
            for cell in cells
        ]
        if len(values) < 5:
            continue

        score_index = None
        for index, value in enumerate(values):
            if extract_score(value) or '-:-' in value:
                score_index = index
                break
        if score_index is None:
            continue

        team_names = []
        for link in row.xpath('.//a[contains(@href, "/verein/")]'):
            name = normalize_text(
                ''.join(link.xpath('./@title'))
                or ' '.join(link.xpath('.//text()'))
            )
            if name:
                team_names.append(name)
        team_names = dedupe_team_names(team_names)

        if len(team_names) >= 2:
            home_name, away_name = team_names[0], team_names[1]
        else:
            before = [
                value for value in values[:score_index]
                if value and not re.search(r'\d{1,2}/\d{1,2}/\d{4}', value)
                and not re.fullmatch(r'\d{1,2}:\d{2}\s*(?:AM|PM)?', value,
                                     re.IGNORECASE)
            ]
            after = [value for value in values[score_index + 1:] if value]
            if not before or not after:
                continue
            home_name, away_name = before[-1], after[-1]

        raw_score = values[score_index]
        date_value = first_match_date(values) or last_date
        time_value = first_match_time(values) or last_time
        if first_match_date(values):
            last_date = first_match_date(values)
        if first_match_time(values):
            last_time = first_match_time(values)

        matches.append({
            'date': date_value,
            'time': time_value,
            'homeTeam': home_name,
            'awayTeam': away_name,
            'score': extract_score(raw_score),
        })

    return matches


def parse_tournament_match_groups(doc: html.HtmlElement) -> List[dict]:
    groups = []
    for index, heading in enumerate(
        doc.xpath('//h2[starts-with(normalize-space(.), "Group ")]'),
        start=1,
    ):
        group_label = normalize_text(' '.join(heading.xpath('.//text()')))
        sibling_tables = following_tables_until_next_group(heading)
        matches = []
        if len(sibling_tables) >= 2:
            matches = parse_tournament_schedule_table(sibling_tables[1])
        elif sibling_tables:
            matches = parse_tournament_schedule_table(sibling_tables[0])

        if not matches:
            continue
        groups.append({
            'key': slugify_key(group_label),
            'label': group_label,
            'order': index,
            'matches': matches,
        })
    return groups


def following_tables_until_next_group(heading: html.HtmlElement) -> List[html.HtmlElement]:
    tables: List[html.HtmlElement] = []
    for sibling in heading.itersiblings():
        if (
            sibling.tag == 'h2'
            and normalize_text(' '.join(sibling.xpath('.//text()'))).startswith('Group ')
        ):
            break
        if sibling.tag == 'table':
            tables.append(sibling)
        tables.extend(sibling.xpath('.//table'))
    return tables


def slugify_key(value: str) -> str:
    normalized = re.sub(r'[^a-z0-9]+', '-', normalize_text(value).casefold())
    return normalized.strip('-')


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
    elif league.family == 'international_tournament':
        doc = html.fromstring(fetch_text(
            session,
            competition_path(league_key, 'gesamtspielplan', season),
            timeout,
        ))
        for group in parse_tournament_match_groups(doc):
            groups[group['key']] = group
    else:
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

    for rank_index, row in enumerate(table[0].xpath('.//tbody/tr[td]'), start=1):
        cells = row.xpath('./td')
        if len(cells) < 7:
            continue

        href = normalize_text(''.join(row.xpath('.//a[contains(@href, "/verein/")]/@href')))
        team_id_match = re.search(r'/verein/(\d+)', href)
        if not team_id_match:
            continue

        team_name = normalize_text(' '.join(cells[2].xpath('.//text()')))
        team_stats = {
            'rank': str(rank_index),
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


def parse_tournament_groups(doc: html.HtmlElement) -> Tuple[List[dict], List[dict]]:
    teams = []
    table_rows = []

    headings = doc.xpath(
        '//h2[starts-with(normalize-space(.), "Group ")]'
    )
    for heading in headings:
        group_label = normalize_text(' '.join(heading.xpath('.//text()')))
        tables = [
            table for table in following_tables_until_next_group(heading)
            if table.xpath(
                './/th[contains(normalize-space(.), "Pts")]'
                ' or .//td[contains(normalize-space(.), "Pts")]'
            )
        ]
        if not tables:
            continue

        for row_index, row in enumerate(tables[0].xpath('.//tbody/tr[td]'), start=1):
            href = normalize_text(''.join(
                row.xpath('.//a[contains(@href, "/verein/")]/@href')
            ))
            if not href:
                continue

            team_id_match = re.search(r'/verein/(\d+)', href)
            if not team_id_match:
                continue

            team_name = normalize_text(
                ''.join(row.xpath('.//a[contains(@href, "/verein/")]/@title'))
            )
            if not team_name:
                team_name = normalize_text(
                    ' '.join(row.xpath('.//a[contains(@href, "/verein/")]//text()'))
                )
            team_name = collapse_repeated_text(team_name)
            if not team_name:
                continue

            values = [
                normalize_text(' '.join(cell.xpath('.//text()')))
                for cell in row.xpath('./td')
            ]
            numeric_values = [
                value for value in values
                if re.fullmatch(r'-?\d+', value or '')
            ]
            rank = numeric_values[0] if numeric_values else str(row_index)
            played = numeric_values[-3] if len(numeric_values) >= 3 else ''
            diff = numeric_values[-2] if len(numeric_values) >= 2 else ''
            points = numeric_values[-1] if numeric_values else ''

            team_stats = {
                'group': group_label,
                'rank': rank,
                'logo': extract_logo_url(row),
                'played': played,
                'wins': '',
                'draws': '',
                'losses': '',
                'goals': '',
                'diff': diff,
                'points': points,
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


def collapse_repeated_text(value: str) -> str:
    text = normalize_text(value)
    midpoint = len(text) // 2
    if len(text) > 2 and len(text) % 2 == 0 and text[:midpoint] == text[midpoint:]:
        return text[:midpoint]
    return text


def fetch_current_table(session: requests.Session, league_key: str,
                        season: int, timeout: int) -> Tuple[List[dict], List[dict]]:
    league = LEAGUES[league_key]
    page = 'tabelle' if league.family == 'domestic' else 'gesamtspielplan'
    doc = html.fromstring(fetch_text(session, competition_path(league_key, page, season), timeout))

    if league.family == 'international_tournament':
        teams, table = parse_tournament_groups(doc)
    elif league.family == 'uefa':
        teams, table = parse_uefa_table(doc)
    else:
        teams, table = parse_domestic_table(doc)

    if not teams or not table:
        raise RuntimeError(
            f'No standings rows found for {league_key} season {season}. '
            'The source page may be unavailable, blocked, or may have changed format.'
        )

    return teams, table


def extract_form_value(row: html.HtmlElement) -> str:
    form_text = normalize_text(' '.join(row.xpath('./td[last()]//text()')))
    return ''.join(character for character in form_text if character in 'WDL')


def fetch_recent_form(session: requests.Session, league_key: str,
                      season: int, timeout: int) -> Dict[str, str]:
    if LEAGUES[league_key].family != 'domestic':
        return {}

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
