"""Validated consistent SQLite backup with independent S3 readback."""
import hashlib
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scripts.backup import backup, validate


def main():
    os.umask(0o077)
    root = Path('/opt/tracy')
    bucket = (root / 'data/backup-bucket').read_text().strip()
    assert bucket == 'tracy-production-322758218105-eu-north-1'
    target = root / 'backups' / ('tracy-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
    backup(root / 'data/tracy.sqlite3', target)
    aws = ['/usr/local/bin/aws', '--region', 'eu-north-1', 's3', 'cp', '--only-show-errors']
    uri = 's3://' + bucket + '/backups/' + target.name
    subprocess.run(aws + [str(target), uri, '--sse', 'AES256'], check=True)
    with tempfile.TemporaryDirectory(prefix='tracy-restore-') as folder:
        restored = Path(folder) / 'restore.sqlite3'
        subprocess.run(aws + [uri, str(restored)], check=True)
        assert hashlib.sha256(restored.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()
        validate(restored)
    for old in sorted(target.parent.glob('tracy-*.sqlite3'))[:-14]:
        old.unlink()
    print('S3 backup and restore verification passed: ' + target.name)


if __name__ == '__main__':
    main()
