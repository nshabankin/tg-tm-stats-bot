from pathlib import Path

from flask import Flask, abort, jsonify, redirect, send_from_directory

from tmstats.catalog import LEAGUES, LEAGUE_KEYS
from tmstats.miniapp import build_league_payload


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
        return jsonify({
            'leagues': [
                {
                    'key': league.key,
                    'label': league.label,
                    'buttonLabel': league.button_label,
                }
                for league in (LEAGUES[key] for key in LEAGUE_KEYS)
            ]
        })

    @app.get('/api/leagues/<league>/snapshot')
    def league_snapshot(league: str):
        if league not in LEAGUES:
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
