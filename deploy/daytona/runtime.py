"""Daytona entrypoint: supervise one API worker and make daily consistent backups."""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

APP = Path('/app')
DATA = APP / 'data'
BACKUPS = APP / 'backups'


def bootstrap():
    from backend.auth.models import Login, Signup
    from backend.main import create_app

    path = DATA / 'owner-bootstrap.json'
    if not path.exists():
        return
    owner = json.loads(path.read_text())
    app = create_app()
    with app.state.db.connect() as conn:
        exists = conn.execute('SELECT 1 FROM users WHERE email=?', (owner['email'],)).fetchone()
    if exists:
        # Recover a bootstrap interrupted after registration, never overwrite an account.
        app.state.auth.login(Login(email=owner['email'], password=owner['password']))
    else:
        app.state.auth.register(Signup(**owner))
    path.unlink()
    print('Production owner initialized.', flush=True)


def make_backup():
    from scripts.backup import backup, validate

    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    local = DATA / ('backup-' + stamp + '.sqlite3')
    backup(DATA / 'tracy.sqlite3', local)
    destination = BACKUPS / local.name
    # S3-backed volume receives a completed file, never a live SQLite database.
    with local.open('rb') as source, destination.open('xb') as target:
        shutil.copyfileobj(source, target)
    restored = DATA / ('restore-check-' + stamp + '.sqlite3')
    shutil.copyfile(destination, restored)
    validate(restored)
    restored.unlink()
    local.unlink()
    print('Verified off-sandbox backup: ' + destination.name, flush=True)


def main():
    os.chdir(APP)
    os.umask(0o077)
    if '--bootstrap' in sys.argv:
        bootstrap()
        return
    if '--backup' in sys.argv:
        make_backup()
        return
    while not (DATA / 'configured').exists():
        time.sleep(2)
    if os.getuid() == 0:
        DATA.mkdir(exist_ok=True)
        os.chown(DATA, 10001, 10001)
        # Daytona's S3 mount has fixed ownership; it does not support chown.
        # Its access is controlled by the sandbox volume attachment.
        BACKUPS.mkdir(exist_ok=True)
        for path in DATA.iterdir():
            if path.is_file():
                os.chown(path, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    subprocess.run([sys.executable, '-m', 'deploy.daytona.runtime', '--bootstrap'], check=True)
    stopping = threading.Event()
    child = None

    def stop(_signum, _frame):
        stopping.set()
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def backups():
        while not stopping.wait(60):
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'deploy.daytona.runtime', '--backup'],
                    timeout=600, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                print('Backup could not complete; retrying in 60 seconds.', flush=True)
                continue
            if result.returncode == 0 and stopping.wait(24 * 60 * 60 - 60):
                return

    threading.Thread(target=backups, daemon=True).start()
    command = [sys.executable, '-m', 'uvicorn', 'backend.main:create_app', '--factory',
               '--host', '0.0.0.0', '--port', '8000', '--workers', '1', '--no-proxy-headers']
    while not stopping.is_set():
        child = subprocess.Popen(command)
        if stopping.is_set():
            child.terminate()
        code = child.wait()
        if stopping.wait(5):
            break
        print(f'API worker exited ({code}); restarting.', flush=True)


if __name__ == '__main__':
    main()
