import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html

from tmstats import (miniapp, refresh, refresh_context, refresh_modes,
                     refresh_pipeline, source)
from tmstats import player_stats
from tmstats.browse import format_table_message
from tmstats.catalog import LEAGUES
from tmstats.refresh_paths import LeagueRefreshPaths, build_league_refresh_paths
from tmstats.snapshots import available_league_keys


class RefreshContextTests(unittest.TestCase):
    def test_current_season_start_year_uses_july_cutover(self) -> None:
        self.assertEqual(
            refresh_context.current_season_start_year(date(2026, 6, 30)),
            2025,
        )
        self.assertEqual(
            refresh_context.current_season_start_year(date(2026, 7, 1)),
            2026,
        )

    def test_build_refresh_context_sets_core_fields_without_session(self) -> None:
        context = refresh_context.build_refresh_context('epl', season=2025)

        self.assertEqual(context.league_key, 'epl')
        self.assertEqual(context.season, 2025)
        self.assertEqual(context.league_label, 'Premier League')
        self.assertIsNone(context.session)
        self.assertEqual(context.paths, build_league_refresh_paths('epl', 2025))

    @patch('tmstats.refresh_context.fetch_recent_form')
    @patch('tmstats.refresh_context.fetch_current_table')
    @patch('tmstats.refresh_context.build_session')
    def test_refresh_live_table_populates_form_and_session(
            self,
            build_session_mock,
            fetch_current_table_mock,
            fetch_recent_form_mock) -> None:
        session = object()
        build_session_mock.return_value = session
        fetch_current_table_mock.return_value = (
            [{'id': '1', 'name': 'Arsenal'}],
            [{'rank': '1', 'club': 'Arsenal'}],
        )
        fetch_recent_form_mock.return_value = {'1': 'WWWWW'}

        context = refresh_context.build_refresh_context('epl', season=2025)
        refreshed = refresh_context.refresh_live_table(context)

        self.assertIs(refreshed.session, session)
        self.assertEqual(refreshed.teams[0]['form'], 'WWWWW')
        self.assertEqual(refreshed.table[0]['form'], 'WWWWW')


class RefreshPipelineTests(unittest.TestCase):
    def test_render_snapshot_pdfs_only_calls_present_rows(self) -> None:
        paths = build_league_refresh_paths('epl', 2025)

        with patch('tmstats.refresh_pipeline.render_snapshot_pdf') as render_mock:
            render_mock.side_effect = [True]

            table_pdf_rendered, stats_pdf_rendered = (
                refresh_pipeline.render_snapshot_pdfs(
                    paths,
                    'Premier League',
                    2025,
                    table_rows=[{'club': 'Arsenal'}],
                    table_changed=True,
                )
            )

        self.assertTrue(table_pdf_rendered)
        self.assertFalse(stats_pdf_rendered)
        render_mock.assert_called_once_with(
            paths.table_pdf,
            'table',
            'Premier League',
            2025,
            [{'club': 'Arsenal'}],
            data_changed=True,
            force=False,
        )

    @patch('tmstats.refresh_pipeline.write_refresh_state')
    def test_write_refresh_summary_returns_result_shape(self, write_state_mock) -> None:
        result = refresh_pipeline.write_refresh_summary(
            'epl',
            2025,
            mode='full',
            clubs=20,
            players=500,
            stats_rows=500,
            table_rows=20,
            matches_payload={'groups': []},
            stats_status='refreshed',
        )

        self.assertEqual(
            result,
            {
                'league': 'epl',
                'season': 2025,
                'clubs': 20,
                'players': 500,
                'stats_rows': 500,
                'table_rows': 20,
            },
        )
        write_state_mock.assert_called_once()

    def test_render_snapshot_pdf_skips_unchanged_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'snapshot.pdf'
            path.write_text('existing')

            with patch('tmstats.refresh_pipeline.render_pdf') as render_pdf_mock:
                rendered = refresh_pipeline.render_snapshot_pdf(
                    path,
                    'table',
                    'Premier League',
                    2025,
                    [{'club': 'Arsenal'}],
                )

        self.assertFalse(rendered)
        render_pdf_mock.assert_not_called()


class TournamentSnapshotTests(unittest.TestCase):
    def test_world_cup_can_build_payload_without_player_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            league_dir = Path(temp_dir) / 'world_cup'
            league_dir.mkdir(parents=True)
            table_path = league_dir / 'world_cup_table_2025.csv'
            table_path.write_text(
                '\n'.join([
                    'group,rank,club,logo,played,wins,draws,losses,goals,diff,points,form',
                    'Group A,1,Mexico,,0,,,,,0,0,',
                    'Group A,2,South Africa,,0,,,,,0,0,',
                    'Group A,3,South Korea,,0,,,,,0,0,',
                    'Group A,4,UEFA Playoff D,,0,,,,,0,0,',
                    'Group B,1,Canada,,0,,,,,0,0,',
                    'Group B,2,Qatar,,0,,,,,0,0,',
                    'Group B,3,Switzerland,,0,,,,,0,0,',
                    'Group B,4,UEFA Playoff A,,0,,,,,0,0,',
                ]),
                encoding='utf-8',
            )

            with patch('tmstats.snapshots.TMSTATS_DIR', Path(temp_dir)):
                self.assertIn('world_cup', available_league_keys(['world_cup']))
                payload = miniapp.build_league_payload('world_cup')

        self.assertEqual(payload['league']['family'], 'international_tournament')
        self.assertEqual(payload['league']['tableLabel'], 'Groups')
        self.assertEqual(len(payload['groups']), 2)
        self.assertEqual(payload['groups'][0]['label'], 'Group A')
        self.assertEqual(payload['groups'][0]['teams'][2]['club'], 'South Korea')
        self.assertEqual(
            [team['club'] for team in payload['thirdPlaceRanking']],
            ['Switzerland', 'South Korea'],
        )

    def test_world_cup_bracket_aliases_resolve_to_table_teams(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            league_dir = Path(temp_dir) / 'world_cup'
            league_dir.mkdir(parents=True)
            table_path = league_dir / 'world_cup_table_2025.csv'
            table_path.write_text(
                '\n'.join([
                    'group,rank,club,logo,played,wins,draws,losses,goals,diff,points,form',
                    'Group A,1,United States,us-flag,3,,,,,4,6,',
                    'Group A,2,Bosnia-Herzegovina,bosnia-flag,3,,,,,-1,4,',
                    'Group A,3,Democratic Republic of the Congo,dr-congo-flag,3,,,,,1,4,',
                ]),
                encoding='utf-8',
            )
            bracket_path = league_dir / 'world_cup_bracket_2025.json'
            bracket_path.write_text(
                json.dumps({
                    'rounds': [{
                        'key': 'round_of_32',
                        'label': 'Round of 32',
                        'ties': [{
                            'code': 'Ro32 1',
                            'matches': [{
                                'homeTeam': 'USA',
                                'awayTeam': 'Bosnia',
                                'result': '2:0',
                            }],
                        }, {
                            'code': 'Ro32 2',
                            'matches': [{
                                'homeTeam': 'DR Congo',
                                'awayTeam': 'Winner QF 1',
                                'result': '',
                            }],
                        }],
                    }],
                }),
                encoding='utf-8',
            )

            with patch('tmstats.snapshots.TMSTATS_DIR', Path(temp_dir)):
                payload = miniapp.build_league_payload('world_cup')

        matches = [
            match
            for round_data in payload['bracket']['rounds']
            for tie in round_data['ties']
            for match in tie['matches']
        ]
        self.assertEqual(matches[0]['homeTeam'], 'United States')
        self.assertEqual(matches[0]['awayTeam'], 'Bosnia-Herzegovina')
        self.assertEqual(matches[1]['homeTeam'], 'Democratic Republic of the Congo')
        self.assertEqual(matches[1]['awayTeam'], 'Winner QF 1')

    def test_tournament_parser_reads_nested_group_tables(self) -> None:
        doc = html.fromstring('''
            <html><body>
              <h2>Group A</h2>
              <div class="grid-view">
                <table>
                  <thead><tr><th>#</th><th>Club</th><th>P</th><th>+/-</th><th>Pts</th></tr></thead>
                  <tbody>
                    <tr>
                      <td>1</td>
                      <td><a title="Mexico" href="/mexico/startseite/verein/6303">Mexico</a></td>
                      <td>0</td><td>0</td><td>0</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div>
                <table>
                  <tbody>
                    <tr>
                      <td>11/06/2026</td>
                      <td>9:00 PM</td>
                      <td><a title="Mexico" href="/mexico/startseite/verein/6303">Mexico</a></td>
                      <td>-:-</td>
                      <td><a title="South Africa" href="/south-africa/startseite/verein/3806">South Africa</a></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <h2>Group B</h2>
            </body></html>
        ''')

        teams, table_rows = source.parse_tournament_groups(doc)
        match_groups = source.parse_tournament_match_groups(doc)

        self.assertEqual(teams[0]['name'], 'Mexico')
        self.assertEqual(table_rows[0]['group'], 'Group A')
        self.assertEqual(match_groups[0]['label'], 'Group A')
        self.assertEqual(match_groups[0]['matches'][0]['homeTeam'], 'Mexico')
        self.assertEqual(match_groups[0]['matches'][0]['awayTeam'], 'South Africa')

    def test_flag_assets_are_upgraded_from_tiny_to_head(self) -> None:
        self.assertEqual(
            source.normalize_asset_url(
                'https://tmssl.akamaized.net//images/flagge/tiny/172.png?lm=1'
            ),
            'https://tmssl.akamaized.net//images/flagge/head/172.png?lm=1',
        )

    def test_world_cup_text_table_is_split_by_group(self) -> None:
        message = format_table_message({
            'league': LEAGUES['world_cup'],
            'table_rows': [
                {'group': 'Group A', 'rank': '1', 'club': 'Mexico',
                 'played': '0', 'points': '0', 'diff': '0'},
                {'group': 'Group A', 'rank': '1', 'club': 'South Africa',
                 'played': '0', 'points': '0', 'diff': '0'},
                {'group': 'Group B', 'rank': '1', 'club': 'Canada',
                 'played': '0', 'points': '0', 'diff': '0'},
            ],
        })

        self.assertIn('World Cup 2026 groups', message)
        self.assertIn('Group A', message)
        self.assertIn('Group B', message)
        self.assertLess(message.index('Group A'), message.index('Mexico'))
        self.assertLess(message.index('Group B'), message.index('Canada'))


class RefreshEntrypointTests(unittest.TestCase):
    def test_run_for_leagues_runs_each_league_and_prints_label(self) -> None:
        calls = []

        def fake_runner(league_key: str, *args, **kwargs) -> dict:
            calls.append((league_key, args, kwargs))
            return {'league': league_key}

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            results = refresh.run_for_leagues(
                ['epl', 'ucl'],
                fake_runner,
                label='Refreshing test mode',
                season=2025,
            )

        self.assertEqual(results, [{'league': 'epl'}, {'league': 'ucl'}])
        self.assertEqual(
            calls,
            [
                ('epl', (), {'season': 2025}),
                ('ucl', (), {'season': 2025}),
            ],
        )
        output = buffer.getvalue()
        self.assertIn('Refreshing test mode for epl season 2025', output)
        self.assertIn('Refreshing test mode for ucl season 2025', output)


class RefreshModesTests(unittest.TestCase):
    def make_paths(self, temp_dir: str, league_key: str = 'epl',
                   season: int = 2025) -> LeagueRefreshPaths:
        league_dir = Path(temp_dir) / league_key
        league_dir.mkdir(parents=True, exist_ok=True)
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

    def test_changed_team_stats_falls_back_to_full_refresh_when_baseline_missing(
            self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            context = SimpleNamespace(
                league_key='epl',
                season=2025,
                timeout=20,
                paths=self.make_paths(temp_dir),
                league_label='Premier League',
            )

            with patch('tmstats.refresh_modes.build_refresh_context',
                       return_value=context), patch(
                           'tmstats.refresh_modes.refresh_league',
                           return_value={'league': 'epl', 'mode': 'full'},
                       ) as refresh_league_mock:
                result = refresh_modes.refresh_changed_team_stats_only(
                    'epl',
                    season=2025,
                    timeout=20,
                    delay=0.5,
                )

        self.assertEqual(result, {'league': 'epl', 'mode': 'full'})
        refresh_league_mock.assert_called_once_with('epl', 2025, 20, 0.5)

    def test_changed_team_stats_skips_player_refresh_when_no_matches_changed(
            self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.make_paths(temp_dir)
            paths.players_csv.write_text('baseline players')
            paths.stats_csv.write_text('baseline stats')
            paths.matches_json.write_text('{}')

            cold_context = SimpleNamespace(
                league_key='epl',
                season=2025,
                timeout=20,
                paths=paths,
                league_label='Premier League',
            )
            live_context = SimpleNamespace(
                league_key='epl',
                season=2025,
                timeout=20,
                paths=paths,
                league_label='Premier League',
                session=object(),
                teams=[{'id': '1', 'name': 'Arsenal'}],
                table=[{'rank': '1', 'club': 'Arsenal'}],
            )

            with patch(
                'tmstats.refresh_modes.build_refresh_context',
                side_effect=[cold_context, live_context],
            ), patch(
                'tmstats.refresh_modes.read_json',
                return_value={'groups': []},
            ), patch(
                'tmstats.refresh_modes.load_existing_players',
                return_value=[{'id': '1', 'club': 'Arsenal'}],
            ), patch(
                'tmstats.refresh_modes.read_csv_rows',
                return_value=[{'club': 'Arsenal'}],
            ), patch(
                'tmstats.refresh_modes.refresh_bracket_snapshot',
                return_value=(None, False),
            ), patch(
                'tmstats.refresh_modes.fetch_match_groups',
                return_value={'groups': []},
            ), patch(
                'tmstats.refresh_modes.detect_updated_match_clubs',
                return_value=[],
            ), patch(
                'tmstats.refresh_modes.write_matches_snapshot',
                return_value=True,
            ), patch(
                'tmstats.refresh_modes.write_table_snapshot',
                return_value=True,
            ), patch(
                'tmstats.refresh_modes.render_snapshot_pdfs',
                return_value=(True, False),
            ), patch(
                'tmstats.refresh_modes.write_refresh_summary',
                return_value={'league': 'epl', 'stats_status': 'skipped'},
            ) as write_summary_mock, patch(
                'tmstats.refresh_modes.fetch_players',
            ) as fetch_players_mock, patch(
                'tmstats.refresh_modes.fetch_stats',
            ) as fetch_stats_mock:
                result = refresh_modes.refresh_changed_team_stats_only(
                    'epl',
                    season=2025,
                    timeout=20,
                    delay=0.5,
                )

        self.assertEqual(result, {'league': 'epl', 'stats_status': 'skipped'})
        fetch_players_mock.assert_not_called()
        fetch_stats_mock.assert_not_called()
        write_summary_mock.assert_called_once()
        self.assertEqual(write_summary_mock.call_args.kwargs['stats_status'], 'skipped')


class PlayerStatsMatcherTests(unittest.TestCase):
    @patch('tmstats.player_stats.fetch_json')
    def test_fetch_players_preserves_existing_roster_on_transient_failure(
            self,
            fetch_json_mock) -> None:
        existing_player = {
            'id': '700106',
            'name': 'Brajan Gruda',
            'shirtNumber': '10',
            'positionId': '3',
            'position': 'Midfield',
            'club': 'RB Leipzig',
            'link': '/brajan-gruda/profil/spieler/700106',
        }
        fetch_json_mock.side_effect = player_stats.requests.HTTPError(
            '502 error'
        )

        players = player_stats.fetch_players(
            object(),
            [{'id': '23826', 'name': 'RB Leipzig'}],
            20,
            delay=0,
            existing_players=[existing_player],
        )

        self.assertEqual(players, [existing_player])

    @patch('tmstats.player_stats.fetch_json')
    def test_fetch_players_skips_failed_team_without_saved_roster(
            self,
            fetch_json_mock) -> None:
        fetch_json_mock.side_effect = player_stats.requests.HTTPError(
            '502 error'
        )

        players = player_stats.fetch_players(
            object(),
            [{'id': '3499', 'name': 'Brazil'}],
            20,
            delay=0,
            existing_players=[],
        )

        self.assertEqual(players, [])

    def test_pick_stats_row_matches_laliga_ea_sports_branding(self) -> None:
        doc = html.fromstring(
            '''
            <table>
              <thead>
                <tr><th>Competition</th><th>Name</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><a href="/laliga-ea-sports/startseite/wettbewerb/ES1">LaLiga EA Sports</a></td>
                  <td>LaLiga EA Sports</td>
                  <td>12</td>
                </tr>
              </tbody>
            </table>
            '''
        )

        cells = player_stats.pick_stats_row(doc, 'la_liga')

        self.assertEqual(cells[0], 'LaLiga EA Sports')

    def test_competition_matches_target_handles_sponsored_variants(self) -> None:
        self.assertTrue(
            player_stats.competition_matches_target(
                {'laligaeasports'},
                {'laliga'},
            )
        )
        self.assertTrue(
            player_stats.competition_matches_target(
                {'laligasantander'},
                {'laliga'},
            )
        )
        self.assertFalse(
            player_stats.competition_matches_target(
                {'copadelrey'},
                {'laliga'},
            )
        )

    def test_build_player_stats_from_api_aggregates_competition_season(self) -> None:
        player = {
            'id': '566723',
            'name': 'Michael Olise',
            'shirtNumber': '17',
            'positionId': '4',
            'position': 'Forward',
            'club': 'Bayern Munich',
        }
        performances = [
            {
                'gameInformation': {
                    'competitionId': 'L1',
                    'seasonId': 2025,
                },
                'clubsInformation': {'club': {'opponentGoalsTotal': 0}},
                'statistics': {
                    'generalStatistics': {'participationState': 'played'},
                    'goalStatistics': {
                        'goalsScoredTotal': 1,
                        'assists': 2,
                    },
                    'cardStatistics': {
                        'yellowCardNet': 1,
                        'yellowRedCard': 0,
                        'redCard': 0,
                    },
                    'playingTimeStatistics': {'playedMinutes': 90},
                },
            },
            {
                'gameInformation': {
                    'competitionId': 'CL',
                    'seasonId': 2025,
                },
                'clubsInformation': {'club': {'opponentGoalsTotal': 1}},
                'statistics': {
                    'generalStatistics': {'participationState': 'played'},
                    'goalStatistics': {
                        'goalsScoredTotal': 4,
                        'assists': 4,
                    },
                    'cardStatistics': {'yellowCardNet': 1},
                    'playingTimeStatistics': {'playedMinutes': 90},
                },
            },
        ]

        row = player_stats.build_player_stats_from_api(
            player,
            performances,
            'bundesliga',
            2025,
            'Bundesliga',
        )

        self.assertEqual(row['played'], '1')
        self.assertEqual(row['goals'], '1')
        self.assertEqual(row['assists'], '2')
        self.assertEqual(row['yellow_cards'], '1')
        self.assertEqual(row['minutes'], "90'")

    @patch('tmstats.player_stats.fetch_text')
    @patch('tmstats.player_stats.fetch_performance_games')
    def test_fetch_stats_preserves_existing_row_on_transient_api_failure(
            self,
            fetch_performance_games_mock,
            fetch_text_mock) -> None:
        existing_row = {
            'player_id': '700106',
            'player_name': 'Brajan Gruda',
            'number': '#10',
            'position': 'Midfield',
            'club': 'RB Leipzig',
            'league': 'Bundesliga',
            'played': '10',
            'goals': '3',
            'assists': '2',
            'yellow_cards': '1',
            'second_yellows': '-',
            'red_cards': '-',
            'conceded': '',
            'clean_sheets': '',
            'minutes': "568'",
        }
        player = {
            'id': '700106',
            'name': 'Brajan Gruda',
            'shirtNumber': '10',
            'positionId': '3',
            'position': 'Midfield',
            'club': 'RB Leipzig',
            'link': '/brajan-gruda/profil/spieler/700106',
        }
        fetch_performance_games_mock.side_effect = RuntimeError('502 error')
        fetch_text_mock.return_value = '''
            <tm-player-performance-table-new data-type="performanceByCompetitions">
            </tm-player-performance-table-new>
        '''

        rows = player_stats.fetch_stats(
            object(),
            'bundesliga',
            [player],
            2025,
            20,
            delay=0,
            existing_rows=[existing_row],
        )

        self.assertEqual(rows, [existing_row])


if __name__ == '__main__':
    unittest.main()
