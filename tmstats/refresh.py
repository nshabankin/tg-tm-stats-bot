import argparse
from typing import Callable, Iterable, List

from .catalog import LEAGUES, LEAGUE_KEYS
from .refresh_context import (DEFAULT_DELAY, DEFAULT_TIMEOUT,
                              current_season_start_year)
from .refresh_modes import (refresh_changed_team_stats_only,
                            refresh_league, refresh_logos_only,
                            refresh_matches_only, render_league_pdfs)


def run_for_leagues(league_keys: Iterable[str],
                    runner: Callable[..., dict],
                    *args,
                    label: str = None,
                    **kwargs) -> List[dict]:
    results = []
    season = kwargs.get('season')
    for league_key in league_keys:
        if label:
            print(f'{label} for {league_key} season {season}', flush=True)
        results.append(runner(league_key, *args, **kwargs))
    return results


def refresh_leagues(league_keys: Iterable[str], season: int = None,
                    timeout: int = DEFAULT_TIMEOUT,
                    delay: float = DEFAULT_DELAY,
                    refresh_rosters: bool = False) -> List[dict]:
    return run_for_leagues(
        league_keys,
        refresh_league,
        season=season,
        timeout=timeout,
        delay=delay,
        refresh_rosters=refresh_rosters,
    )


def refresh_matches_for_leagues(league_keys: Iterable[str], season: int = None,
                                timeout: int = DEFAULT_TIMEOUT,
                                delay: float = DEFAULT_DELAY) -> List[dict]:
    return run_for_leagues(
        league_keys,
        refresh_matches_only,
        label='Refreshing match snapshots',
        season=season,
        timeout=timeout,
        delay=delay,
    )


def refresh_changed_team_stats_for_leagues(
        league_keys: Iterable[str], season: int = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY) -> List[dict]:
    return run_for_leagues(
        league_keys,
        refresh_changed_team_stats_only,
        season=season,
        timeout=timeout,
        delay=delay,
    )


def refresh_logos_for_leagues(league_keys: Iterable[str],
                              season: int = None,
                              timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    return run_for_leagues(
        league_keys,
        refresh_logos_only,
        label='Refreshing logos',
        season=season,
        timeout=timeout,
    )


def render_pdfs_for_leagues(league_keys: Iterable[str],
                            season: int = None) -> List[dict]:
    return run_for_leagues(
        league_keys,
        render_league_pdfs,
        label='Rendering PDFs',
        season=season,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Refresh current Transfermarkt snapshots for one or more leagues.'
    )
    parser.add_argument(
        '--league',
        action='append',
        choices=sorted(LEAGUE_KEYS),
        help='League key to refresh. Repeat the flag to refresh multiple leagues.',
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Refresh all supported leagues.',
    )
    parser.add_argument(
        '--season',
        type=int,
        default=current_season_start_year(),
        help='Transfermarkt season start year. Defaults to the current European season.',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=DEFAULT_TIMEOUT,
        help='HTTP timeout in seconds for each request.',
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=DEFAULT_DELAY,
        help='Optional delay in seconds between requests.',
    )
    parser.add_argument(
        '--pdf-only',
        action='store_true',
        help='Generate PDFs from existing CSV snapshots without refreshing data.',
    )
    parser.add_argument(
        '--matches-only',
        action='store_true',
        help='Refresh match/bracket JSON snapshots without scraping players.',
    )
    parser.add_argument(
        '--changed-team-stats',
        action='store_true',
        help=(
            'Refresh table/matches, then scrape only clubs involved in newly '
            'completed or changed matches.'
        ),
    )
    parser.add_argument(
        '--logos-only',
        action='store_true',
        help='Refresh only team logo URLs in existing table CSV snapshots.',
    )
    parser.add_argument(
        '--refresh-rosters',
        action='store_true',
        help='Force a fresh roster pull instead of reusing the saved players CSV.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    league_keys = args.league or []

    if args.all or not league_keys:
        league_keys = list(LEAGUES)

    if args.logos_only:
        results = refresh_logos_for_leagues(
            league_keys,
            season=args.season,
            timeout=args.timeout,
        )
        completion_label = 'Logo refresh complete'
    elif args.changed_team_stats:
        results = refresh_changed_team_stats_for_leagues(
            league_keys,
            season=args.season,
            timeout=args.timeout,
            delay=args.delay,
        )
        completion_label = 'Changed-team refresh complete'
    elif args.pdf_only:
        results = render_pdfs_for_leagues(league_keys, season=args.season)
        completion_label = 'PDF render complete'
    elif args.matches_only:
        results = refresh_matches_for_leagues(
            league_keys,
            season=args.season,
            timeout=args.timeout,
            delay=args.delay,
        )
        completion_label = 'Match snapshot refresh complete'
    else:
        results = refresh_leagues(
            league_keys,
            season=args.season,
            timeout=args.timeout,
            delay=args.delay,
            refresh_rosters=args.refresh_rosters,
        )
        completion_label = 'Refresh complete'

    print()
    print(completion_label)
    for result in results:
        print(
            f'- {result["league"]}: '
            f'{result["clubs"]} clubs, '
            f'{result["players"]} players, '
            f'{result["stats_rows"]} stats rows, '
            f'{result["table_rows"]} table rows'
        )


if __name__ == '__main__':
    main()
