#!/usr/bin/env python3
"""
Quick sanity check for TM_COOKIE.

This does a single lightweight GET against a league table page and reports
whether Transfermarkt responds with an AWS WAF captcha challenge.
"""

import argparse

from tmstats.catalog import LEAGUES
from tmstats.refresh_context import current_season_start_year
from tmstats.source import build_session, competition_path, request_with_retries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--league",
        default="epl",
        help="League key to test (default: epl).",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Season start year (default: current European season).",
    )
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    season = args.season or current_season_start_year()
    page = 'tabelle' if LEAGUES[args.league].family == 'domestic' else 'gesamtspielplan'
    url = competition_path(args.league, page, season)

    session = build_session()
    try:
        resp = request_with_retries(session, url, timeout=args.timeout)
    except RuntimeError as e:
        print("WAF_BLOCKED:", str(e))
        return 2

    print("OK:", resp.status_code, "bytes=", len(resp.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
