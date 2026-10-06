#!/bin/bash
set -euo pipefail
umask 027
cd /opt/tracy
aws --region eu-north-1 s3 cp s3://tracy-production-322758218105-eu-north-1/release/current.tar.gz /opt/tracy/release.tar.gz --only-show-errors
# Source archive contains only an explicit application allowlist, never credentials or databases.
tar -xzf release.tar.gz
rm release.tar.gz
/opt/tracy-tools/bin/uv sync --locked --no-dev --no-editable --python /usr/bin/python3
# The service runs unprivileged; uv creates the environment under root's umask.
chgrp -R tracy /opt/tracy/.venv
chmod -R g+rX /opt/tracy/.venv
aws --region eu-north-1 ssm get-parameter --name /tracy/production/config --with-decryption --query Parameter.Value --output text > /opt/tracy/.env
chown root:tracy /opt/tracy/.env
chmod 640 /opt/tracy/.env
chown -R tracy:tracy /opt/tracy/data
chmod 750 /opt/tracy/data
cp deploy/aws/tracy.service deploy/aws/tracy-backup.service deploy/aws/tracy-backup.timer /etc/systemd/system/
cp deploy/aws/Caddyfile /etc/caddy/Caddyfile
printf '%s\n' tracy-production-322758218105-eu-north-1 > data/backup-bucket
chmod 640 data/backup-bucket
chown tracy:tracy data/backup-bucket
systemctl daemon-reload
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl enable tracy.service tracy-backup.timer
# API starts only after the verified production database is migrated.
echo 'Release installed; awaiting the production database.'
