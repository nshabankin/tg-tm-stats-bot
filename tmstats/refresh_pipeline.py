from pathlib import Path
from typing import List, Optional, Tuple

from .pdf_export import render_pdf
from .player_stats import PLAYER_FIELDS, STATS_FIELDS
from .refresh_paths import LeagueRefreshPaths
from .refresh_state import write_refresh_state
from .storage import write_csv, write_json

TABLE_FIELDS = ['rank', 'club', 'logo', 'played', 'wins', 'draws',
                'losses', 'goals', 'diff', 'points', 'form']


def render_snapshot_pdf(path: Path, snapshot_type: str,
                        league_label: str, season: int,
                        rows: List[dict],
                        data_changed: bool = False,
                        force: bool = False) -> bool:
    if not force and not data_changed and path.exists():
        return False
    render_pdf(path, snapshot_type, league_label, season, rows)
    return True


def write_players_snapshot(paths: LeagueRefreshPaths,
                           players: List[dict]) -> bool:
    return write_csv(paths.players_csv, players, PLAYER_FIELDS)


def write_stats_snapshot(paths: LeagueRefreshPaths,
                         stats_rows: List[dict]) -> bool:
    return write_csv(paths.stats_csv, stats_rows, STATS_FIELDS)


def write_table_snapshot(paths: LeagueRefreshPaths,
                         table_rows: List[dict]) -> bool:
    return write_csv(paths.table_csv, table_rows, TABLE_FIELDS)


def write_matches_snapshot(paths: LeagueRefreshPaths,
                           matches_payload: Optional[dict]) -> bool:
    return write_json(paths.matches_json, matches_payload)


def render_snapshot_pdfs(paths: LeagueRefreshPaths,
                         league_label: str,
                         season: int,
                         *,
                         table_rows: Optional[List[dict]] = None,
                         stats_rows: Optional[List[dict]] = None,
                         table_changed: bool = False,
                         stats_changed: bool = False,
                         force: bool = False) -> Tuple[bool, bool]:
    table_pdf_rendered = False
    if table_rows is not None:
        table_pdf_rendered = render_snapshot_pdf(
            paths.table_pdf,
            'table',
            league_label,
            season,
            table_rows,
            data_changed=table_changed,
            force=force,
        )

    stats_pdf_rendered = False
    if stats_rows is not None:
        stats_pdf_rendered = render_snapshot_pdf(
            paths.stats_pdf,
            'stats',
            league_label,
            season,
            stats_rows,
            data_changed=stats_changed,
            force=force,
        )

    return table_pdf_rendered, stats_pdf_rendered


def build_refresh_result(league_key: str, season: int, *,
                         clubs: int, players: int,
                         stats_rows: int, table_rows: int) -> dict:
    return {
        'league': league_key,
        'season': season,
        'clubs': clubs,
        'players': players,
        'stats_rows': stats_rows,
        'table_rows': table_rows,
    }


def write_refresh_summary(league_key: str, season: int, mode: str, *,
                          clubs: int, players: int,
                          stats_rows: int, table_rows: int,
                          matches_payload: Optional[dict] = None,
                          **state_kwargs) -> dict:
    write_refresh_state(
        league_key,
        season,
        mode=mode,
        clubs=clubs,
        players=players,
        stats_rows=stats_rows,
        table_rows=table_rows,
        matches_payload=matches_payload,
        **state_kwargs,
    )
    return build_refresh_result(
        league_key,
        season,
        clubs=clubs,
        players=players,
        stats_rows=stats_rows,
        table_rows=table_rows,
    )
