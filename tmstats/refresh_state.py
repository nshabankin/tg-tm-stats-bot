from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from config import TMSTATS_DIR

from .incremental import matchday_number_from_key
from .storage import write_json


def refresh_state_path(league_key: str, season: int) -> Path:
    return TMSTATS_DIR / league_key / f'{league_key}_refresh_state_{season}.json'


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def summarize_match_payload(payload: Optional[dict]) -> dict:
    groups = (payload or {}).get('groups', [])
    pending_matchdays: List[int] = []
    completed_matchdays: List[int] = []

    for group in groups:
        matchday = matchday_number_from_key(group.get('key', ''))
        if matchday is None:
            continue
        matches = group.get('matches', [])
        if not matches:
            continue
        if any(not (match.get('score') or '').strip() for match in matches):
            pending_matchdays.append(matchday)
        else:
            completed_matchdays.append(matchday)

    return {
        'groupCount': len(groups),
        'pendingMatchdays': pending_matchdays,
        'completedMatchdays': completed_matchdays,
        'lastPendingMatchday': max(pending_matchdays) if pending_matchdays else None,
        'lastCompletedMatchday': (
            max(completed_matchdays) if completed_matchdays else None
        ),
    }


def write_refresh_state(league_key: str, season: int, *,
                        mode: str,
                        clubs: int,
                        players: int,
                        stats_rows: int,
                        table_rows: int,
                        matches_payload: Optional[dict] = None,
                        changed_clubs: Optional[Iterable[str]] = None,
                        resolved_clubs: Optional[Iterable[str]] = None,
                        unresolved_clubs: Optional[Iterable[str]] = None,
                        stats_status: str = '',
                        table_changed: bool = False,
                        players_changed: bool = False,
                        stats_changed: bool = False,
                        matches_changed: bool = False,
                        bracket_changed: bool = False,
                        table_pdf_rendered: bool = False,
                        stats_pdf_rendered: bool = False) -> bool:
    payload = {
        'league': league_key,
        'season': season,
        'updatedAt': utc_timestamp(),
        'mode': mode,
        'counts': {
            'clubs': clubs,
            'players': players,
            'statsRows': stats_rows,
            'tableRows': table_rows,
        },
        'matches': summarize_match_payload(matches_payload),
        'stats': {
            'status': stats_status,
            'changedClubs': list(changed_clubs or []),
            'resolvedClubs': list(resolved_clubs or []),
            'unresolvedClubs': list(unresolved_clubs or []),
        },
        'outputs': {
            'tableChanged': table_changed,
            'playersChanged': players_changed,
            'statsChanged': stats_changed,
            'matchesChanged': matches_changed,
            'bracketChanged': bracket_changed,
            'tablePdfRendered': table_pdf_rendered,
            'statsPdfRendered': stats_pdf_rendered,
        },
    }
    return write_json(refresh_state_path(league_key, season), payload)
