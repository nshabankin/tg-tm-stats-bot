from dataclasses import dataclass
from pathlib import Path

from config import TMSTATS_DIR


@dataclass(frozen=True)
class LeagueRefreshPaths:
    league_key: str
    season: int
    league_dir: Path
    players_csv: Path
    stats_csv: Path
    table_csv: Path
    matches_json: Path
    bracket_json: Path
    table_pdf: Path
    stats_pdf: Path


def build_league_refresh_paths(league_key: str, season: int) -> LeagueRefreshPaths:
    league_dir = TMSTATS_DIR / league_key
    return LeagueRefreshPaths(
        league_key=league_key,
        season=season,
        league_dir=league_dir,
        players_csv=league_dir / f'{league_key}_players_{season}.csv',
        stats_csv=league_dir / f'{league_key}_stats_{season}.csv',
        table_csv=league_dir / f'{league_key}_table_{season}.csv',
        matches_json=league_dir / f'{league_key}_matches_{season}.json',
        bracket_json=league_dir / f'{league_key}_bracket_{season}.json',
        table_pdf=league_dir / f'{league_key}_table_{season}.pdf',
        stats_pdf=league_dir / f'{league_key}_stats_{season}.pdf',
    )
