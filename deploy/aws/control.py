"""Small AWS CLI helpers. No secret values should be passed in command arguments."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/aws-deployment'
AWS = str(Path.home() / '.local/bin/aws')


def aws(*args, input=None):
    command = [AWS, *args, '--profile', 'tracy', '--region', 'eu-north-1', '--no-cli-pager']
    r = subprocess.run(command, input=input, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode())
    return json.loads(r.stdout) if r.stdout.strip() else None


def instance():
    s = aws('cloudformation', 'describe-stacks', '--stack-name', 'tracy-production')['Stacks'][0]
    outputs = {o['OutputKey']: o['OutputValue'] for o in s.get('Outputs', [])}
    if outputs:
        p = PRIVATE / 'infrastructure.json'
        p.write_text(json.dumps({'status': s['StackStatus'], **outputs}, indent=2));p.chmod(0o600)
    return outputs


def send(commands, comment='Tracy deployment'):
    info = instance()
    result = aws('ssm', 'send-command', '--instance-ids', info['InstanceId'],
                 '--document-name', 'AWS-RunShellScript', '--comment', comment,
                 '--parameters', json.dumps({'commands': commands, 'executionTimeout': ['600']}))
    cid = result['Command']['CommandId']
    print(json.dumps({'command_id': cid, 'instance_id': info['InstanceId']}), flush=True)
    return cid


def result(cid):
    r = aws('ssm', 'get-command-invocation', '--command-id', cid, '--instance-id', instance()['InstanceId'])
    print(json.dumps({k: r.get(k) for k in ['Status', 'ResponseCode', 'StandardOutputContent', 'StandardErrorContent']}), flush=True)
    return r
