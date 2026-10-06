"""Daily validated SQLite backup on the backend host, with bounded retention."""
from datetime import UTC, datetime
from pathlib import Path
from scripts.backup import backup


def main():
    root = Path.home() / 'tracy-backend'
    target = root / 'backups' / ('tracy-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '.sqlite3')
    backup(root / 'data/tracy.sqlite3', target)
    target.chmod(0o600)
    for old in sorted(target.parent.glob('tracy-*.sqlite3'))[:-14]:
        old.unlink()
    print('Validated local backup: ' + target.name)


if __name__ == '__main__':
    main()
