import re
from typing import Iterable, List, Optional, Tuple

from .identity import canonical_club_identity, names_loosely_match, normalize_text


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


def resolve_team_names(changed_names: Iterable[str],
                       teams: List[dict]) -> Tuple[List[dict], List[str]]:
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

    for group in (existing_payload or {}).get('groups', []):
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
