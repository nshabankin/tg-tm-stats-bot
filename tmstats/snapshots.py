import re
from pathlib import Path

from config import TMSTATS_DIR


FILE_TYPES = {
    'table': {
        'label': 'League Table',
        'suffix': 'table',
    },
    'players': {
        'label': 'Players',
        'suffix': 'players',
    },
    'stats': {
        'label': 'Player Stats',
        'suffix': 'stats',
    },
}

FORMAT_TYPES = {
    'csv': {
        'label': 'CSV',
        'extension': 'csv',
    },
    'pdf': {
        'label': 'PDF',
        'extension': 'pdf',
    },
}


def extract_snapshot_year(filename: str) -> int:
    match = re.search(r'_(stats|table|players)_(\d{4})\.(csv|pdf)$', filename)
    if not match:
        return 0
    return int(match.group(2))


def get_latest_snapshot_file(league: str, file_type: str,
                             file_format: str) -> Path:
    league_dir = TMSTATS_DIR / league
    suffix = FILE_TYPES[file_type]['suffix']
    extension = FORMAT_TYPES[file_format]['extension']
    snapshot_files = sorted(
        league_dir.glob(f'{league}_{suffix}_*.{extension}'),
        key=lambda path: (extract_snapshot_year(path.name), path.stat().st_mtime),
        reverse=True,
    )

    if not snapshot_files:
        raise FileNotFoundError(
            f'No {file_type} {file_format} snapshots found for {league}'
        )

    return snapshot_files[0]


def league_has_snapshots(league: str,
                         required_file_types=('table', 'players', 'stats')) -> bool:
    try:
        for file_type in required_file_types:
            get_latest_snapshot_file(league, file_type, 'csv')
    except FileNotFoundError:
        return False
    return True


def available_league_keys(league_keys) -> list:
    return [
        league_key
        for league_key in league_keys
        if league_has_snapshots(league_key)
    ]
