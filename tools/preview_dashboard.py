"""Serve a loopback-only preview using a disposable database and demo credentials."""
import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5055)
    parser.add_argument('--extra-site-packages', default='')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if args.extra_site_packages:
        sys.path.append(str(Path(args.extra_site_packages).resolve()))
    os.environ.update(PYTHON_DOTENV_DISABLED='1', DASH_USER='preview', DASH_PASSWORD='preview-only',
                      DASH_SECRET_KEY='local-preview-only', DASH_SESSION_SECURE='false', DASH_TRUST_PROXY='false')
    from flask import render_template
    from data.database.dashboard.app import create_app
    import core.cache_db as db

    with tempfile.TemporaryDirectory(prefix='pytonazz-preview-') as tmp:
        path = Path(tmp) / 'cache.db'
        db.rebuild_database(path)
        db.init_db(db_path=str(path), enabled=True)
        for i, (title, artist) in enumerate([
            ('Midnight City', 'M83'), ('Instant Crush', 'Daft Punk'),
            ('L\'amour toujours', 'Gigi D\'Agostino'), ('Intro', 'The xx'),
            ('Tadow', 'Masego & FKJ'), ('A Walk', 'Tycho'),
        ]):
            db.put(title + ' ' + artist, dict(title=title, artist=artist,
                   webpage_url=f'https://www.youtube.com/watch?v=demo{i}', source='youtube',
                   duration=180+i*23, thumbnail='', spotify_url=''))
        app = create_app(str(path))
        @app.route('/preview-dj')
        def preview_dj():
            return render_template('dj_console.html', guild_id=123)
        app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
