import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tmstats import refresh, refresh_context, refresh_pipeline
from tmstats.refresh_paths import build_league_refresh_paths


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


if __name__ == '__main__':
    unittest.main()
