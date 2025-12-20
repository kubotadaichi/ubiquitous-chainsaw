locals {
  redis_url = "redis://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"

  user_data = <<EOF
#!/bin/bash
set -euxo pipefail

LOG=/var/log/user-data.log
exec > >(tee -a "$LOG" | logger -t user-data -s 2>/dev/console) 2>&1

AWS_REGION="${var.aws_region}"
S3_BUCKET="${aws_s3_bucket.assets.bucket}"
REDIS_URL="${local.redis_url}"
REPO_URL="${var.repo_url}"
REPO_REF="${var.repo_ref}"

if command -v dnf >/dev/null 2>&1; then
  dnf update -y
  dnf install -y git docker
  dnf install -y docker-compose-plugin || true
else
  yum update -y
  yum install -y git docker
  yum install -y docker-compose-plugin || true
fi

systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  ARCH="$(uname -m)"
  curl -L -o /usr/local/bin/docker-compose "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-$ARCH"
  chmod +x /usr/local/bin/docker-compose
  ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose || true
fi

APP_DIR=/opt/pipeline
if [ ! -d "$APP_DIR/.git" ]; then
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch --all --prune
git checkout "$REPO_REF" || git checkout -B "$REPO_REF" "origin/$REPO_REF"

cat > "$APP_DIR/.env.cloud" <<'ENV'
AWS_REGION=$AWS_REGION
S3_BUCKET=$S3_BUCKET
REDIS_URL=$REDIS_URL
ENV

cat > /usr/local/bin/pipeline-up.sh <<'SH'
#!/bin/bash
set -euo pipefail
cd /opt/pipeline
/usr/bin/docker compose -f docker-compose.cloud.yml --env-file .env.cloud up -d --build
SH
chmod +x /usr/local/bin/pipeline-up.sh

cat > /etc/systemd/system/pipeline.service <<'UNIT'
[Unit]
Description=Pipeline (hub + worker) via docker compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/pipeline-up.sh
ExecStop=/usr/bin/docker compose -f /opt/pipeline/docker-compose.cloud.yml --env-file /opt/pipeline/.env.cloud down

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now pipeline.service
EOF
}
