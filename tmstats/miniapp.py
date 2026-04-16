import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .browse import get_team_players, load_league_snapshot, parse_int
from .snapshots import extract_snapshot_year


def slugify(value: str) -> str:
    normalized = re.sub(r'[^a-z0-9]+', '-', (value or '').casefold())
    return normalized.strip('-')


def parse_stat_int(value: object) -> int:
    normalized = str(value or '').strip()
    if not normalized or normalized == '-':
        return 0
    digits = re.sub(r'[^0-9]', '', normalized)
    return int(digits) if digits else 0


def parse_goals_pair(value: str) -> tuple[int, int]:
    parts = (value or '').split(':', 1)
    if len(parts) != 2:
        return 0, 0
    return parse_int(parts[0]), parse_int(parts[1])


def season_label(start_year: int) -> str:
    if not start_year:
        return ''
    return f'{start_year}/{(start_year + 1) % 100:02d}'


def player_highlight(player: Optional[dict], stat_key: str = '') -> dict:
    if not player:
        return {}

    stats = player.get('stats') or {}
    return {
        'id': player.get('id', ''),
        'name': player.get('name', ''),
        'club': player.get('club', ''),
        'position': player.get('position', ''),
        'shirtNumber': player.get('shirtNumber', ''),
        'value': stats.get(stat_key, '') if stat_key else '',
    }


def best_player(players: List[dict], stat_key: str) -> Optional[dict]:
    ranked = sorted(
        players,
        key=lambda player: (
            parse_stat_int((player.get('stats') or {}).get(stat_key, '')),
            parse_stat_int((player.get('stats') or {}).get('minutes', '')),
            player.get('name', ''),
        ),
        reverse=True,
    )
    if not ranked:
        return None
    top_player = ranked[0]
    if parse_stat_int((top_player.get('stats') or {}).get(stat_key, '')) <= 0:
        return None
    return top_player


def serialize_player(player: dict) -> dict:
    stats = player.get('stats') or {}
    return {
        'id': player.get('id', ''),
        'name': player.get('name', ''),
        'shirtNumber': player.get('shirtNumber', ''),
        'position': player.get('position', ''),
        'club': player.get('club', ''),
        'link': player.get('link', ''),
        'stats': {
            'played': stats.get('played', ''),
            'goals': stats.get('goals', ''),
            'assists': stats.get('assists', ''),
            'yellowCards': stats.get('yellow_cards', ''),
            'secondYellows': stats.get('second_yellows', ''),
            'redCards': stats.get('red_cards', ''),
            'conceded': stats.get('conceded', ''),
            'cleanSheets': stats.get('clean_sheets', ''),
            'minutes': stats.get('minutes', ''),
        },
    }


def serialize_team(team_row: dict, players: List[dict]) -> dict:
    goals_for, goals_against = parse_goals_pair(team_row.get('goals', ''))
    return {
        'slug': slugify(team_row.get('club', '')),
        'rank': parse_int(team_row.get('rank')),
        'club': team_row.get('club', ''),
        'logo': team_row.get('logo', ''),
        'played': parse_int(team_row.get('played')),
        'wins': parse_int(team_row.get('wins')),
        'draws': parse_int(team_row.get('draws')),
        'losses': parse_int(team_row.get('losses')),
        'goals': team_row.get('goals', ''),
        'goalsFor': goals_for,
        'goalsAgainst': goals_against,
        'diff': parse_int(team_row.get('diff')),
        'points': parse_int(team_row.get('points')),
        'form': team_row.get('form', ''),
        'playerCount': len(players),
        'players': [serialize_player(player) for player in players],
    }


def build_snapshot_meta(snapshot: dict) -> dict:
    paths = snapshot['paths']
    season_start_year = extract_snapshot_year(paths['table'].name)
    updated_at = max(path.stat().st_mtime for path in paths.values())
    return {
        'seasonStartYear': season_start_year,
        'seasonLabel': season_label(season_start_year),
        'updatedAt': datetime.fromtimestamp(
            updated_at, tz=timezone.utc
        ).isoformat().replace('+00:00', 'Z'),
        'source': 'Local CSV snapshot',
    }


def load_bracket_snapshot(table_path, league: str, season_start_year: int) -> dict:
    if not season_start_year or not table_path:
        return {'rounds': []}

    # Reuse the league directory already selected by the latest table snapshot so
    # bracket files stay season-aligned with the payload users are viewing.
    bracket_path = table_path.with_name(f'{league}_bracket_{season_start_year}.json')
    if not bracket_path.exists():
        return {'rounds': []}

    with bracket_path.open(encoding='utf-8') as json_file:
        return json.load(json_file)


def build_highlights(teams: List[dict]) -> dict:
    all_players = [
        player
        for team in teams
        for player in team.get('players', [])
    ]
    leader = teams[0] if teams else None
    top_scoring_club = max(
        teams,
        key=lambda team: (team.get('goalsFor', 0), team.get('points', 0)),
        default=None,
    )
    return {
        'leader': {
            'club': leader.get('club', ''),
            'points': leader.get('points', 0),
        } if leader else {},
        'topScoringClub': {
            'club': top_scoring_club.get('club', ''),
            'goals': top_scoring_club.get('goalsFor', 0),
        } if top_scoring_club else {},
        'topScorer': player_highlight(best_player(all_players, 'goals'), 'goals'),
        'topAssister': player_highlight(
            best_player(all_players, 'assists'), 'assists'
        ),
        'ironMan': player_highlight(best_player(all_players, 'minutes'), 'minutes'),
        'clubs': len(teams),
        'players': len(all_players),
    }


def build_league_payload(league: str) -> Dict[str, object]:
    snapshot = load_league_snapshot(league)
    teams = []
    meta = build_snapshot_meta(snapshot)
    bracket = load_bracket_snapshot(
        snapshot['paths']['table'],
        league,
        meta['seasonStartYear'],
    )

    for row in snapshot['table_rows']:
        players = get_team_players(snapshot, row)
        teams.append(serialize_team(row, players))

    return {
        'league': {
            'key': snapshot['league'].key,
            'label': snapshot['league'].label,
            'buttonLabel': snapshot['league'].button_label,
            'logoUrl': snapshot['league'].logo_url,
            'family': snapshot['league'].family,
            'tableLabel': snapshot['league'].table_label,
            'supportsBracket': snapshot['league'].supports_bracket,
        },
        'meta': meta,
        'highlights': build_highlights(teams),
        'table': [
            {
                'rank': team['rank'],
                'club': team['club'],
                'logo': team['logo'],
                'played': team['played'],
                'wins': team['wins'],
                'draws': team['draws'],
                'losses': team['losses'],
                'goals': team['goals'],
                'diff': team['diff'],
                'points': team['points'],
                'form': team['form'],
                'slug': team['slug'],
            }
            for team in teams
        ],
        'teams': teams,
        'bracket': bracket,
    }
