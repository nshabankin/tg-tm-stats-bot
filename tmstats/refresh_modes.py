from typing import Optional, Tuple

from .catalog import LEAGUES
from .identity import canonical_club_identity, club_identity
from .incremental import detect_updated_match_clubs, resolve_team_names
from .player_stats import (fetch_players, fetch_stats, load_existing_players,
                           pick_stats_output, replace_players_for_clubs,
                           replace_stats_for_clubs)
from .refresh_context import (DEFAULT_DELAY, DEFAULT_TIMEOUT, RefreshContext,
                              build_refresh_context)
from .refresh_pipeline import (render_snapshot_pdfs, write_matches_snapshot,
                               write_players_snapshot,
                               write_refresh_summary, write_stats_snapshot,
                               write_table_snapshot)
from .source import fetch_current_table, fetch_knockout_bracket, fetch_match_groups
from .storage import read_csv_rows, read_json, write_json


def refresh_bracket_snapshot(context: RefreshContext) -> Tuple[Optional[dict], bool]:
    if not LEAGUES[context.league_key].supports_bracket:
        return None, False

    try:
        bracket_payload = fetch_knockout_bracket(
            context.session,
            context.league_key,
            context.season,
            context.timeout,
        )
        bracket_changed = write_json(context.paths.bracket_json, bracket_payload)
        return bracket_payload, bracket_changed
    except Exception as error:
        print(f'Warning: failed to refresh knockout bracket for {context.league_key}: '
              f'{error}', flush=True)
        return None, False


def refresh_league(league_key: str, season: int = None,
                   timeout: int = DEFAULT_TIMEOUT,
                   delay: float = DEFAULT_DELAY,
                   refresh_rosters: bool = False) -> dict:
    context = build_refresh_context(
        league_key,
        season=season,
        timeout=timeout,
        with_live_table=True,
    )

    print(f'Refreshing {league_key} for season {context.season}', flush=True)

    players = []
    players_changed = False
    if not refresh_rosters:
        players = load_existing_players(context.paths.players_csv)
        if players:
            print(f'  reusing {len(players)} players from saved roster',
                  flush=True)

    if not players:
        players = fetch_players(context.session, context.teams, timeout, delay)
        players_changed = write_players_snapshot(context.paths, players)
        print(f'  fetched {len(context.teams)} teams and {len(players)} players',
              flush=True)

    existing_stats = read_csv_rows(context.paths.stats_csv) if context.paths.stats_csv.exists() else []
    stats = fetch_stats(
        context.session,
        league_key,
        players,
        context.season,
        timeout,
        teams=context.teams,
        delay=delay,
        existing_rows=existing_stats,
    )
    stats_output = pick_stats_output(stats, existing_stats, league_key)

    stats_changed = write_stats_snapshot(context.paths, stats_output)
    table_changed = write_table_snapshot(context.paths, context.table)
    bracket_payload, bracket_changed = refresh_bracket_snapshot(context)

    matches_payload = None
    matches_changed = False
    try:
        matches_payload = fetch_match_groups(
            context.session,
            league_key,
            context.season,
            timeout,
            bracket=bracket_payload,
            teams=context.teams,
            club_count=len(context.table),
            delay=delay,
        )
        matches_changed = write_matches_snapshot(context.paths, matches_payload)
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: '
              f'{error}', flush=True)
    table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        context.paths,
        context.league_label,
        context.season,
        table_rows=context.table,
        stats_rows=stats_output,
        table_changed=table_changed,
        stats_changed=stats_changed,
    )

    return write_refresh_summary(
        league_key,
        context.season,
        mode='full',
        clubs=len(context.teams),
        players=len(players),
        stats_rows=len(stats_output),
        table_rows=len(context.table),
        matches_payload=matches_payload,
        stats_status='preserved' if stats_output == existing_stats else 'refreshed',
        table_changed=table_changed,
        players_changed=players_changed,
        stats_changed=stats_changed,
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def render_league_pdfs(league_key: str, season: int = None) -> dict:
    context = build_refresh_context(league_key, season=season)

    missing = [path.name for path in (context.paths.table_csv, context.paths.stats_csv)
               if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f'Missing CSV snapshots for {league_key} season {context.season}: '
            f'{", ".join(missing)}'
        )

    table_rows = read_csv_rows(context.paths.table_csv)
    stats_rows = read_csv_rows(context.paths.stats_csv)
    table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        context.paths,
        context.league_label,
        context.season,
        table_rows=table_rows,
        stats_rows=stats_rows,
        force=True,
    )
    matches_payload = read_json(context.paths.matches_json) if context.paths.matches_json.exists() else None

    return write_refresh_summary(
        league_key,
        context.season,
        mode='pdf-only',
        clubs=len(table_rows),
        players=len(stats_rows),
        stats_rows=len(stats_rows),
        table_rows=len(table_rows),
        matches_payload=matches_payload,
        stats_status='unchanged',
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def refresh_changed_team_stats_only(
        league_key: str, season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> dict:
    context = build_refresh_context(league_key, season=season, timeout=timeout)

    if not (context.paths.players_csv.exists() and context.paths.stats_csv.exists() and context.paths.matches_json.exists()):
        print(
            f'Refreshing changed-team stats for {league_key} for season {context.season}',
            flush=True,
        )
        print(
            '  missing baseline snapshots; falling back to a full league refresh',
            flush=True,
        )
        return refresh_league(league_key, context.season, timeout, delay)

    context = build_refresh_context(
        league_key,
        season=context.season,
        timeout=timeout,
        with_live_table=True,
    )
    print(f'Refreshing changed-team stats for {league_key} for season {context.season}',
          flush=True)

    existing_matches = read_json(context.paths.matches_json)
    existing_players = load_existing_players(context.paths.players_csv)
    existing_stats = read_csv_rows(context.paths.stats_csv)

    bracket_payload, bracket_changed = refresh_bracket_snapshot(context)

    latest_matches = fetch_match_groups(
        context.session,
        league_key,
        context.season,
        timeout,
        bracket=bracket_payload,
        teams=context.teams,
        club_count=len(context.table),
        existing_payload=existing_matches,
        delay=delay,
    )
    changed_clubs = detect_updated_match_clubs(existing_matches, latest_matches)

    matches_changed = write_matches_snapshot(context.paths, latest_matches)
    table_changed = write_table_snapshot(context.paths, context.table)
    table_pdf_rendered, _stats_pdf_rendered = render_snapshot_pdfs(
        context.paths,
        context.league_label,
        context.season,
        table_rows=context.table,
        table_changed=table_changed,
    )

    if not changed_clubs:
        print('  no newly completed or changed matches; player stats unchanged',
              flush=True)
        return write_refresh_summary(
            league_key,
            context.season,
            mode='changed-team-stats',
            clubs=len(context.teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(context.table),
            matches_payload=latest_matches,
            stats_status='skipped',
            table_changed=table_changed,
            stats_changed=False,
            matches_changed=matches_changed,
            bracket_changed=bracket_changed,
            table_pdf_rendered=table_pdf_rendered,
        )

    targeted_teams, unresolved_clubs = resolve_team_names(changed_clubs, context.teams)

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
        return write_refresh_summary(
            league_key,
            context.season,
            mode='changed-team-stats',
            clubs=len(context.teams),
            players=len(existing_players),
            stats_rows=len(existing_stats),
            table_rows=len(context.table),
            matches_payload=latest_matches,
            changed_clubs=changed_clubs,
            unresolved_clubs=unresolved_clubs,
            stats_status='unresolved',
            table_changed=table_changed,
            stats_changed=False,
            matches_changed=matches_changed,
            bracket_changed=bracket_changed,
            table_pdf_rendered=table_pdf_rendered,
        )

    print(
        f'  refreshing players/stats for {len(targeted_teams)} club(s): '
        f'{", ".join(team["name"] for team in targeted_teams)}',
        flush=True,
    )

    replacement_players = fetch_players(context.session, targeted_teams, timeout, delay)
    targeted_club_ids = {
        canonical_club_identity(team.get('name', ''))
        for team in targeted_teams
    }
    players_output = replace_players_for_clubs(
        existing_players,
        replacement_players,
        targeted_club_ids,
    )
    players_changed = write_players_snapshot(context.paths, players_output)

    targeted_existing_stats = [
        row for row in existing_stats
        if canonical_club_identity(row.get('club', '')) in targeted_club_ids
    ]
    replacement_stats = fetch_stats(
        context.session,
        league_key,
        replacement_players,
        context.season,
        timeout,
        teams=context.teams,
        delay=delay,
        existing_rows=targeted_existing_stats,
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
    stats_changed = write_stats_snapshot(context.paths, stats_output)
    _table_pdf_rendered, stats_pdf_rendered = render_snapshot_pdfs(
        context.paths,
        context.league_label,
        context.season,
        stats_rows=stats_output,
        stats_changed=stats_changed,
    )
    return write_refresh_summary(
        league_key,
        context.season,
        mode='changed-team-stats',
        clubs=len(context.teams),
        players=len(players_output),
        stats_rows=len(stats_output),
        table_rows=len(context.table),
        matches_payload=latest_matches,
        changed_clubs=changed_clubs,
        resolved_clubs=[team.get('name', '') for team in targeted_teams],
        unresolved_clubs=unresolved_clubs,
        stats_status='preserved' if stats_output == existing_stats else 'targeted',
        table_changed=table_changed,
        players_changed=players_changed,
        stats_changed=stats_changed,
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
        table_pdf_rendered=table_pdf_rendered,
        stats_pdf_rendered=stats_pdf_rendered,
    )


def refresh_matches_only(league_key: str, season: int = None,
                         timeout: int = DEFAULT_TIMEOUT,
                         delay: float = DEFAULT_DELAY) -> dict:
    context = build_refresh_context(
        league_key,
        season=season,
        timeout=timeout,
        with_live_table=True,
    )
    existing_matches = (
        read_json(context.paths.matches_json)
        if context.paths.matches_json.exists()
        else None
    )

    bracket_payload, bracket_changed = refresh_bracket_snapshot(context)
    table_changed = write_table_snapshot(context.paths, context.table)

    matches_payload = existing_matches
    matches_changed = False
    try:
        matches_payload = fetch_match_groups(
            context.session,
            league_key,
            context.season,
            timeout,
            bracket=bracket_payload,
            teams=context.teams,
            club_count=len(context.table),
            existing_payload=existing_matches,
            delay=delay,
        )
        matches_changed = write_matches_snapshot(context.paths, matches_payload)
    except Exception as error:
        print(f'Warning: failed to refresh match list for {league_key}: {error}', flush=True)

    return write_refresh_summary(
        league_key,
        context.season,
        mode='matches-only',
        clubs=len(context.table),
        players=0,
        stats_rows=0,
        table_rows=len(context.table),
        matches_payload=matches_payload,
        stats_status='skipped',
        table_changed=table_changed,
        matches_changed=matches_changed,
        bracket_changed=bracket_changed,
    )


def refresh_logos_only(league_key: str, season: int = None,
                       timeout: int = DEFAULT_TIMEOUT) -> dict:
    context = build_refresh_context(
        league_key,
        season=season,
        timeout=timeout,
        with_session=True,
    )
    if not context.paths.table_csv.exists():
        raise FileNotFoundError(
            f'Missing table snapshot for {league_key} season {context.season}: '
            f'{context.paths.table_csv.name}'
        )

    _, latest_table = fetch_current_table(
        context.session,
        league_key,
        context.season,
        timeout,
    )
    latest_by_club = {club_identity(row['club']): row for row in latest_table}
    latest_by_rank = {row['rank']: row for row in latest_table}
    current_rows = read_csv_rows(context.paths.table_csv)

    updated_rows = []
    for row in current_rows:
        latest = latest_by_club.get(club_identity(row.get('club', '')))
        if not latest:
            latest = latest_by_rank.get(row.get('rank', ''))
        updated_rows.append({
            **row,
            'logo': latest.get('logo', '') if latest else row.get('logo', ''),
        })

    table_changed = write_table_snapshot(context.paths, updated_rows)
    table_pdf_rendered, _stats_pdf_rendered = render_snapshot_pdfs(
        context.paths,
        context.league_label,
        context.season,
        table_rows=updated_rows,
        table_changed=table_changed,
    )
    matches_payload = read_json(context.paths.matches_json) if context.paths.matches_json.exists() else None

    return write_refresh_summary(
        league_key,
        context.season,
        mode='logos-only',
        clubs=len(updated_rows),
        players=0,
        stats_rows=0,
        table_rows=len(updated_rows),
        matches_payload=matches_payload,
        stats_status='skipped',
        table_changed=table_changed,
        table_pdf_rendered=table_pdf_rendered,
    )
