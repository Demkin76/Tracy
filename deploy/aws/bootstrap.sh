#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y python3-venv curl unzip gnupg caddy
curl -fsSL https://awscli.amazonaws.com/v2/install.sh -o /tmp/install-aws-cli.sh
bash /tmp/install-aws-cli.sh --system --quiet
id tracy >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/tracy --shell /usr/sbin/nologin tracy
install -d -m 750 -o tracy -g tracy /opt/tracy/data /opt/tracy/backups
python3 -m venv /opt/tracy-tools
/opt/tracy-tools/bin/pip install --disable-pip-version-check uv==0.12.23
# No default/public site before the reviewed Tracy release is installed.
systemctl stop caddy
systemctl disable caddy
install -d /var/lib/tracy
printf '%s\n' ready > /var/lib/tracy/bootstrap-ready
