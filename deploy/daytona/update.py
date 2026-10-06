"""Roll out an already-built app to the existing sandbox, preserving data and keys.

No dependency changes: those require a new image. Keeps a remote code rollback
and a verified off-sandbox database backup. Never downloads production SQLite.
"""

import hashlib
import json
import os
import shlex
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import certifi
from dotenv import dotenv_values

from deploy.daytona.deploy import NAME, PRIVATE, ROOT, image_context, save_private


REMOTE = r'''
import hashlib, json, os, shutil, signal, sqlite3, subprocess, sys, time
from pathlib import Path
import httpx

app=Path('/app'); release=sys.argv[1]; checksum=sys.argv[2]
stage=app/'releases'/release/'next'; previous=stage.parent/'previous'
archive=app/'data'/('release-'+release+'.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest()==checksum, 'Archive checksum mismatch'
import tarfile
with tarfile.open(archive) as package:
    package.extractall(stage, filter='data')
assert (app/'uv.lock').read_bytes()==(stage/'uv.lock').read_bytes(), 'Dependency update needs a new image'
for path in stage.rglob('*'):
    path.chmod(0o755 if path.is_dir() else 0o644)
subprocess.run([sys.executable, '-m', 'compileall', '-q', str(stage/'backend')], check=True)

def worker():
    result=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        try:
            args=(path/'cmdline').read_bytes().split(b'\0')
            if len(args)>3 and args[1:4]==[b'-m', b'uvicorn', b'backend.main:create_app']:
                result.append(int(path.name))
        except OSError: pass
    assert len(result)==1, 'Expected exactly one API worker'
    pid=result[0]
    parent=int(next(line.split()[1] for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith('PPid:')))
    args=Path(f'/proc/{parent}/cmdline').read_bytes().split(b'\0')
    assert args[1:3]==[b'-m', b'deploy.daytona.runtime'], 'Unexpected supervisor'
    return pid,parent

def halt(pid):
    os.kill(pid, signal.SIGTERM)
    for _ in range(150):
        try:
            state=Path(f'/proc/{pid}/stat').read_text().split()[2]
            if state=='Z': return
        except FileNotFoundError: return
        time.sleep(.1)
    raise RuntimeError('Worker did not stop gracefully; rollout cancelled')

def healthy():
    for _ in range(45):
        try:
            r=httpx.get('http://127.0.0.1:8000/readyz', timeout=2)
            if r.status_code==200 and r.json().get('ready'): return True
        except (httpx.HTTPError,ValueError): pass
        time.sleep(1)
    return False

def identity():
    with sqlite3.connect(app/'data/tracy.sqlite3') as conn:
        return dict(conn.execute('SELECT key,value FROM metadata')),conn.execute('SELECT count(*) FROM users').fetchone()[0]

before=identity()
# Back up with the same UID as the application; the database stays in Daytona.
def app_uid():
    os.setgroups([]);os.setgid(10001);os.setuid(10001)
subprocess.run([sys.executable,'-m','deploy.daytona.runtime','--backup'],cwd=app,preexec_fn=app_uid,check=True,timeout=120)
previous.mkdir(parents=True)
env=app/'data/production.env'
shutil.copy2(env,previous/'production.env')
os.chmod(previous/'production.env',0o600)
names=['backend','sdk','scripts','examples','frontend/dist','deploy/daytona/runtime.py','pyproject.toml','uv.lock']
# Container image layers may reject directory rename with EXDEV. Copy the
# rollback first, then replace source trees while the API worker is stopped.
for name in names:
    old=app/name; saved=previous/name
    saved.parent.mkdir(parents=True,exist_ok=True)
    if old.is_dir(): shutil.copytree(old,saved)
    elif old.exists(): shutil.copy2(old,saved)
moved=[]
pid,parent=worker()
os.kill(parent,signal.SIGSTOP)
try:
    halt(pid)
    # Keep older hashed assets for browser tabs already open during the release.
    for asset in (app/'frontend/dist/assets').glob('*'):
        if asset.is_file() and not (stage/'frontend/dist/assets'/asset.name).exists():
            shutil.copy2(asset,stage/'frontend/dist/assets'/asset.name)
    for name in names:
        old=app/name; saved=previous/name; new=stage/name
        moved.append(name)
        if old.is_dir(): shutil.rmtree(old)
        elif old.exists(): old.unlink()
        new.rename(old)
    lines=[line for line in env.read_text().splitlines() if not line.startswith('POA_ADAPTIVE_DEVNET_ANCHORS_ENABLED=')]
    temp=env.with_suffix('.next')
    temp.write_text('\n'.join(lines+['POA_ADAPTIVE_DEVNET_ANCHORS_ENABLED=true'])+'\n')
    os.chmod(temp,0o600);os.chown(temp,10001,10001);temp.replace(env)
except BaseException:
    for name in reversed(moved):
        old=app/name; saved=previous/name
        if old.exists():
            if old.is_dir():shutil.rmtree(old)
            else:old.unlink()
        if saved.exists():saved.rename(old)
    shutil.copy2(previous/'production.env',env);os.chown(env,10001,10001)
    raise
finally:
    os.kill(parent,signal.SIGCONT)
if not healthy():
    raise RuntimeError('Release not healthy; previous code is retained at '+str(previous)+'. Inspect supervisor before rollback.')
assert before==identity(), 'Database identity or user count changed'
response=httpx.get('http://127.0.0.1:8000/v1/adaptive/capabilities').json()
assert response['forward_worker_enabled'] and response['devnet_anchors_enabled'] and not response['mainnet_enabled']
archive.unlink()
print(json.dumps({'release':release,'ready':True,'identity_preserved':True,'capabilities':response,'rollback':str(previous)}))
'''


def main():
    os.umask(0o077)
    os.environ['SSL_CERT_FILE'] = certifi.where()
    from daytona import Daytona, DaytonaConfig

    values = dotenv_values(ROOT / '.env')
    sandbox = Daytona(DaytonaConfig(api_key=values['DAYTONA_API_KEY'],
                                   target=values.get('DAYTONA_TARGET', 'eu'))).get(NAME)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    with tempfile.TemporaryDirectory(prefix='tracy-release-') as directory:
        stage = Path(directory) / 'source'
        stage.mkdir()
        image_context(stage)
        archive = Path(directory) / 'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as package:
            for path in sorted(stage.iterdir()):
                package.add(path, arcname=path.name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        sandbox.fs.upload_file(str(archive), f'/app/data/release-{stamp}.tar.gz')
        command = '/app/.venv/bin/python -c ' + shlex.quote(REMOTE) + ' ' + shlex.quote(stamp) + ' ' + checksum
        result = sandbox.process.exec(command, cwd='/app', timeout=240)
        print(result.result, flush=True)
        if result.exit_code:
            raise SystemExit('Rollout did not finish; inspect remote rollback before retrying.')
    evidence = json.loads(result.result.strip().splitlines()[-1])
    save_private(PRIVATE / 'adaptive-release.json', json.dumps(evidence, indent=2))
    # Mirror just the applied non-secret flag; preserve existing recovery keys.
    path = PRIVATE / 'production.env'
    lines = [line for line in path.read_text().splitlines()
             if not line.startswith('POA_ADAPTIVE_DEVNET_ANCHORS_ENABLED=')]
    save_private(path, '\n'.join(lines + ['POA_ADAPTIVE_DEVNET_ANCHORS_ENABLED=true']) + '\n')


if __name__ == '__main__':
    main()
