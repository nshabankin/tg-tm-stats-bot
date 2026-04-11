import re
from typing import Dict, List

from .browse import get_team_players, load_league_snapshot, parse_int


def slugify(value: str) -> str:
    normalized = re.sub(r'[^a-z0-9]+', '-', (value or '').casefold())
    return normalized.strip('-')


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
        'diff': parse_int(team_row.get('diff')),
        'points': parse_int(team_row.get('points')),
        'form': team_row.get('form', ''),
        'playerCount': len(players),
        'players': [serialize_player(player) for player in players],
    }


def build_league_payload(league: str) -> Dict[str, object]:
    snapshot = load_league_snapshot(league)
    teams = []

    for row in snapshot['table_rows']:
        players = get_team_players(snapshot, row)
        teams.append(serialize_team(row, players))

    return {
        'league': {
            'key': snapshot['league'].key,
            'label': snapshot['league'].label,
            'buttonLabel': snapshot['league'].button_label,
        },
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
    }
