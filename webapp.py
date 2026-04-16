from pathlib import Path

from flask import Flask, abort, jsonify, redirect, send_from_directory

from tmstats.catalog import LEAGUES, LEAGUE_KEYS
from tmstats.miniapp import build_league_payload
from tmstats.snapshots import available_league_keys


BASE_DIR = Path(__file__).resolve().parent
MINIAPP_DIR = BASE_DIR / 'miniapp'


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(MINIAPP_DIR),
        static_url_path='/mini/static',
    )

    @app.get('/')
    def root():
        return redirect('/mini/', code=302)

    @app.get('/health')
    def health():
        return jsonify({'ok': True})

    @app.get('/api/leagues')
    def leagues():
        visible_keys = available_league_keys(LEAGUE_KEYS)
        return jsonify({
            'leagues': [
                {
                    'key': league.key,
                    'label': league.label,
                    'buttonLabel': league.button_label,
                    'logoUrl': league.logo_url,
                    'family': league.family,
                    'tableLabel': league.table_label,
                    'supportsBracket': league.supports_bracket,
                }
                for league in (LEAGUES[key] for key in visible_keys)
            ]
        })

    @app.get('/api/leagues/<league>/snapshot')
    def league_snapshot(league: str):
        if league not in LEAGUES or league not in available_league_keys(LEAGUE_KEYS):
            abort(404)
        return jsonify(build_league_payload(league))

    @app.get('/mini/')
    @app.get('/mini')
    def miniapp_index():
        return send_from_directory(MINIAPP_DIR, 'index.html')

    @app.get('/mini/<path:_path>')
    def miniapp_static(_path: str):
        target = MINIAPP_DIR / _path
        if target.exists() and target.is_file():
            return send_from_directory(MINIAPP_DIR, _path)
        return send_from_directory(MINIAPP_DIR, 'index.html')

    return app
