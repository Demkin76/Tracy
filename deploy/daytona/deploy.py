"""Deploy the current build to one private, persistent Daytona sandbox.

Run with the Daytona SDK, python-dotenv and certifi installed. Credentials are read
from the ignored root .env; production secrets are kept in data/daytona-production.
"""

import base64
import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import certifi
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/daytona-production'
NAME = 'tracy-production'


def save_private(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as output:
        os.chmod(temporary, 0o600)
        output.write(value)
    temporary.replace(path)


def prepare_config(source):
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = PRIVATE / 'production.env'
    if path.exists():
        if not (PRIVATE / 'owner.json').exists():
            raise RuntimeError('Production owner recovery file is missing; do not recreate credentials.')
        return
    existing = json.loads((ROOT / 'data/tracy-owner.json').read_text())
    owner = {'email': existing['email'], 'name': existing.get('name', 'Tracy owner'),
             'password': secrets.token_urlsafe(32)}
    values = {
        'POA_SIGNING_SEED': base64.b64encode(secrets.token_bytes(32)).decode(),
        'POA_EXECUTION_WALLET_SEED': base64.b64encode(secrets.token_bytes(32)).decode(),
        'POA_DATABASE_PATH': '/app/data/tracy.sqlite3',
        'POA_CONTROL_RESOURCES_PATH': '/app/data/resources.json',
        'POA_CONTROL_CREDENTIALS_PATH': '/app/data/credentials.json',
        'POA_ENVIRONMENT': 'production', 'POA_COOKIE_SECURE': 'true',
        'POA_DEVNET_ENABLED': 'false', 'POA_SIGNUP_ENABLED': 'false',
        'POA_ALLOWED_HOSTS': json.dumps(['tracys.online', '127.0.0.1', 'localhost']),
        'POA_CORS_ORIGINS': json.dumps(['https://tracys.online']),
    }
    for key in ('POA_GEMINI_API_KEY', 'POA_GEMINI_API_KEY_2', 'POA_GEMINI_MODEL', 'POA_COPILOT_PROVIDER'):
        if source.get(key):
            values[key] = source[key]
    save_private(PRIVATE / 'owner.json', json.dumps(owner))
    save_private(path, '\n'.join(f'{k}={v}' for k, v in values.items()) + '\n')


def image_context(directory):
    # An explicit allowlist avoids uploading .env, databases, browser state or git.
    for name in ('backend', 'sdk', 'scripts', 'examples', 'frontend/dist'):
        shutil.copytree(ROOT / name, directory / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env*'))
    for name in ('pyproject.toml', 'uv.lock', 'deploy/daytona/runtime.py'):
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    shutil.copyfile(ROOT / 'deploy/daytona/Dockerfile', directory / 'Dockerfile')


def main():
    os.umask(0o077)
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    # aiohttp constructs its default SSL contexts when imported by the SDK.
    from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Image, Resources, VolumeMount

    source = dotenv_values(ROOT / '.env')
    client = Daytona(DaytonaConfig(api_key=source['DAYTONA_API_KEY'],
                                  target=source.get('DAYTONA_TARGET', 'eu')))
    matches = [s for s in client.list() if s.name == NAME]
    if matches and not (PRIVATE / 'production.env').exists():
        raise RuntimeError('Existing sandbox found without local production secrets. Recover them first.')
    prepare_config(source)
    if matches:
        sandbox = client.get(matches[0].id)
        print('Reusing existing sandbox:', sandbox.id, flush=True)
        if sandbox.state.value in ('stopped', 'archived'):
            sandbox.start(timeout=120)
        elif sandbox.state.value != 'started':
            sandbox.wait_for_sandbox_start(timeout=1200)
    else:
        volume = client.volume.get('tracy-production-backups', create=True)
        save_private(PRIVATE / 'resources.json', json.dumps({'backup_volume_id': volume.id}))
        with tempfile.TemporaryDirectory(prefix='tracy-daytona-') as temporary:
            stage = Path(temporary)
            image_context(stage)
            print('Building production image; source context excludes secrets and local data.', flush=True)
            sandbox = client.create(
                CreateSandboxFromImageParams(
                    name=NAME, image=Image.from_dockerfile(stage / 'Dockerfile', strict_context=True),
                    resources=Resources(cpu=1, memory=1, disk=5), os_user='root',
                    public=False, ephemeral=False,
                    auto_stop_interval=0, auto_delete_interval=-1, ttl_minutes=0,
                    labels={'app': 'tracy', 'environment': 'production'},
                    volumes=[VolumeMount(volume_id=volume.id, mount_path='/app/backups')],
                ), timeout=1200,
                on_snapshot_create_logs=lambda chunk: print(chunk, end='', flush=True),
            )
    save_private(PRIVATE / 'sandbox.json', json.dumps({'id': sandbox.id, 'name': NAME}))
    print('Sandbox ready:', sandbox.id, flush=True)
    link = sandbox.get_preview_link(8000)
    origin = link.url.rstrip('/')
    host = urlsplit(origin).hostname
    if not host or urlsplit(origin).scheme != 'https':
        raise RuntimeError('Invalid Daytona origin')
    save_private(PRIVATE / 'edge-secrets.json', json.dumps({
        'DAYTONA_ORIGIN': origin, 'DAYTONA_PREVIEW_TOKEN': link.token,
    }))
    values = dict(dotenv_values(PRIVATE / 'production.env'))
    values['POA_ALLOWED_HOSTS'] = json.dumps(['tracys.online', '127.0.0.1', 'localhost', host])
    save_private(PRIVATE / 'production.env', '\n'.join(f'{k}={v}' for k, v in values.items()) + '\n')
    check = sandbox.process.exec('test -e /app/data/configured', timeout=15)
    if check.exit_code != 0:
        sandbox.fs.upload_file(str(PRIVATE / 'production.env'), '/app/data/production.env')
        sandbox.fs.upload_file(str(PRIVATE / 'owner.json'), '/app/data/owner-bootstrap.json')
        result = sandbox.process.exec(
            'chmod 600 /app/data/production.env /app/data/owner-bootstrap.json && touch /app/data/configured',
            timeout=15,
        )
        if result.exit_code != 0:
            raise RuntimeError('Could not activate production configuration')
    print('Configuration ready. Owner password and preview token saved locally; never printed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # SDK errors can include request details. Redact all local credential values.
        message = str(error)
        for file in (ROOT / '.env', PRIVATE / 'production.env'):
            if file.exists():
                for key, value in dotenv_values(file).items():
                    if value and any(part in key for part in ('KEY', 'TOKEN', 'SEED', 'PASSWORD')):
                        message = message.replace(value, '[redacted]')
        print(type(error).__name__ + ': ' + message, file=sys.stderr)
        sys.exit(1)
