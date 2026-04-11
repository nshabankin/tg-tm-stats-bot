import csv
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .catalog import LEAGUES
from .snapshots import get_latest_snapshot_file

TEAM_PAGE_SIZE = 10
PLAYER_PAGE_SIZE = 12


def read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline='', encoding='utf-8') as csv_file:
        return list(csv.DictReader(csv_file))


def normalize_key(*parts: str) -> Tuple[str, ...]:
    return tuple((part or '').strip().casefold() for part in parts)


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_number(value: str) -> str:
    return (value or '').replace('#', '').strip()


def shirt_sort_key(player: dict) -> Tuple[int, int, str]:
    shirt_number = normalize_number(player.get('shirtNumber', ''))
    if shirt_number.isdigit():
        return (0, int(shirt_number), player.get('name', ''))
    return (1, 999, player.get('name', ''))


def sort_table_rows(rows: List[dict]) -> List[dict]:
    return sorted(rows, key=lambda row: parse_int(row.get('rank')))


def compact_form(form: str, width: int = 5) -> str:
    normalized = (form or '').strip()
    if not normalized:
        return '-'
    if len(normalized) <= width:
        return normalized
    return normalized[-width:]


def compact_club_name(name: str, width: int = 15) -> str:
    compact = (name or '').strip()
    replacements = [
        ('Brighton & Hove Albion', 'Brighton'),
        ('Nottingham Forest', 'Nottm Forest'),
        ('Manchester United', 'Man United'),
        ('Manchester City', 'Man City'),
        ('Tottenham Hotspur', 'Tottenham'),
        ('Crystal Palace', 'C Palace'),
        ('Newcastle United', 'Newcastle'),
        ('West Ham United', 'West Ham'),
        ('Leicester City', 'Leicester'),
        ('Aston Villa', 'A Villa'),
        ('Wolverhampton Wanderers', 'Wolves'),
        ('AFC Bournemouth', 'Bournemouth'),
    ]
    for original, shortened in replacements:
        if compact == original:
            compact = shortened
            break

    for suffix in (' FC', ' AFC', ' CF'):
        if compact.endswith(suffix):
            compact = compact[:-len(suffix)]
            break

    if len(compact) <= width:
        return compact

    words = compact.split()
    if len(words) > 1:
        compact = ' '.join(word[:3] if index == 0 else word
                           for index, word in enumerate(words))
    return compact[:width].rstrip()


def build_stats_lookup(stats_rows: List[dict]) -> Tuple[Dict[str, dict], Dict[Tuple[str, ...], dict]]:
    by_player_id = {}
    by_fallback = {}

    for row in stats_rows:
        player_id = (row.get('player_id') or '').strip()
        if player_id:
            by_player_id[player_id] = row

        fallback_key = normalize_key(
            row.get('player_name', ''),
            row.get('club', ''),
            normalize_number(row.get('number', '')),
        )
        by_fallback[fallback_key] = row

    return by_player_id, by_fallback


def latest_data_paths(league: str) -> Dict[str, Path]:
    return {
        'table': get_latest_snapshot_file(league, 'table', 'csv'),
        'players': get_latest_snapshot_file(league, 'players', 'csv'),
        'stats': get_latest_snapshot_file(league, 'stats', 'csv'),
    }


def load_league_snapshot(league: str) -> dict:
    paths = latest_data_paths(league)
    table_rows = sort_table_rows(read_csv_rows(paths['table']))
    player_rows = read_csv_rows(paths['players'])
    stats_rows = read_csv_rows(paths['stats'])
    stats_by_id, stats_by_fallback = build_stats_lookup(stats_rows)

    players_by_team: Dict[str, List[dict]] = {}
    players_by_id: Dict[str, dict] = {}

    for player in player_rows:
        player_id = (player.get('id') or '').strip()
        fallback_key = normalize_key(
            player.get('name', ''),
            player.get('club', ''),
            normalize_number(player.get('shirtNumber', '')),
        )
        stats = stats_by_id.get(player_id) or stats_by_fallback.get(fallback_key)
        enriched_player = {
            **player,
            'stats': stats,
        }
        players_by_team.setdefault(player.get('club', ''), []).append(enriched_player)
        if player_id:
            players_by_id[player_id] = enriched_player

    for team_players in players_by_team.values():
        team_players.sort(key=shirt_sort_key)

    return {
        'league': LEAGUES[league],
        'table_rows': table_rows,
        'players_by_team': players_by_team,
        'players_by_id': players_by_id,
        'paths': paths,
    }


def get_team_row(snapshot: dict, rank: str) -> Optional[dict]:
    return next(
        (row for row in snapshot['table_rows'] if row.get('rank') == str(rank)),
        None,
    )


def get_team_players(snapshot: dict, team_row: dict) -> List[dict]:
    return snapshot['players_by_team'].get(team_row.get('club', ''), [])


def format_table_message(snapshot: dict) -> str:
    league_label = snapshot['league'].label
    header = f'{league_label} table\nLatest local snapshot'
    lines = [
        '# Club            P  W  D  L GF:GA  GD Pts Form',
    ]

    for row in snapshot['table_rows']:
        club = compact_club_name(row.get('club', ''))
        lines.append(
            f'{parse_int(row.get("rank")):>2} '
            f'{club:<15} '
            f'{parse_int(row.get("played")):>2} '
            f'{parse_int(row.get("wins")):>2} '
            f'{parse_int(row.get("draws")):>2} '
            f'{parse_int(row.get("losses")):>2} '
            f'{row.get("goals", ""):<5} '
            f'{row.get("diff", ""):>3} '
            f'{row.get("points", ""):>3} '
            f'{compact_form(row.get("form", "")):<5}'
        )

    return f'<b>{escape(header)}</b>\n<pre>{escape(chr(10).join(lines))}</pre>'


def format_team_summary(team_row: dict, players: List[dict]) -> str:
    return '\n'.join([
        f'<b>{escape(team_row.get("club", ""))}</b>',
        f'Position: {escape(team_row.get("rank", "-"))}',
        (
            'Record: '
            f'{escape(team_row.get("wins", "-"))}-'
            f'{escape(team_row.get("draws", "-"))}-'
            f'{escape(team_row.get("losses", "-"))}'
        ),
        (
            'Played: '
            f'{escape(team_row.get("played", "-"))} | '
            f'Goals: {escape(team_row.get("goals", "-"))} | '
            f'Pts: {escape(team_row.get("points", "-"))}'
        ),
        f'Form: {escape(team_row.get("form", "-") or "-")}',
        f'Players in snapshot: {len(players)}',
        '',
        'Choose a player:',
    ])


def stat_line(label: str, value: str) -> Optional[str]:
    normalized = (value or '').strip()
    if not normalized or normalized == '-':
        return None
    return f'<b>{escape(label)}:</b> {escape(normalized)}'


def format_player_message(player: dict, team_row: dict) -> str:
    stats = player.get('stats') or {}
    lines = [
        f'<b>{escape(player.get("name", ""))}</b>',
        (
            f'{escape(player.get("position", "Unknown"))}'
            + (f' | #{escape(player.get("shirtNumber", ""))}'
               if player.get('shirtNumber') else '')
        ),
        escape(team_row.get('club', '')),
        '',
    ]

    stat_lines = [
        stat_line('Played', stats.get('played', '')),
        stat_line('Goals', stats.get('goals', '')),
        stat_line('Assists', stats.get('assists', '')),
        stat_line('Yellow cards', stats.get('yellow_cards', '')),
        stat_line('Second yellows', stats.get('second_yellows', '')),
        stat_line('Red cards', stats.get('red_cards', '')),
        stat_line('Conceded', stats.get('conceded', '')),
        stat_line('Clean sheets', stats.get('clean_sheets', '')),
        stat_line('Minutes', stats.get('minutes', '')),
    ]

    lines.extend(line for line in stat_lines if line)

    if len(lines) == 4:
        lines.append('No detailed stat row is available in the current snapshot.')

    return '\n'.join(lines)
