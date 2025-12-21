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
REPO_SUBDIR="${var.repo_subdir}"

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
git fetch origin --prune
if git show-ref --verify --quiet "refs/remotes/origin/$REPO_REF"; then
  git checkout -B "$REPO_REF" "origin/$REPO_REF"
else
  if git checkout "$REPO_REF"; then
    true
  else
    echo "ERROR: repo_ref not found: $REPO_REF" >&2
    echo "Remote branches:" >&2
    git branch -r >&2 || true
    exit 1
  fi
fi

WORK_DIR="$APP_DIR"
if [ -n "$REPO_SUBDIR" ]; then
  WORK_DIR="$APP_DIR/$REPO_SUBDIR"
fi

if [ ! -f "$WORK_DIR/docker-compose.cloud.yml" ]; then
  echo "ERROR: docker-compose.cloud.yml not found at: $WORK_DIR/docker-compose.cloud.yml" >&2
  echo "Hint: set Terraform var repo_subdir to the directory that contains docker-compose.cloud.yml" >&2
  exit 1
fi

cat > "$WORK_DIR/.env.cloud" <<ENV
AWS_REGION=$AWS_REGION
S3_BUCKET=$S3_BUCKET
REDIS_URL=$REDIS_URL
ENV

cat > /usr/local/bin/pipeline-up.sh <<'SH'
#!/bin/bash
set -euo pipefail
WORK_DIR=/opt/pipeline
if [ -f /opt/pipeline/.repo_subdir ]; then
  SUBDIR="$(cat /opt/pipeline/.repo_subdir || true)"
  if [ -n "$SUBDIR" ]; then
    WORK_DIR="/opt/pipeline/$SUBDIR"
  fi
fi
cd "$WORK_DIR"
if docker compose version >/dev/null 2>&1; then
  docker compose -f docker-compose.cloud.yml --env-file "$WORK_DIR/.env.cloud" up -d --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f docker-compose.cloud.yml --env-file "$WORK_DIR/.env.cloud" up -d --build
else
  echo "ERROR: docker compose / docker-compose not found" >&2
  exit 1
fi
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
ExecStop=/bin/bash -lc 'WORK_DIR=/opt/pipeline; if [ -f /opt/pipeline/.repo_subdir ]; then SUBDIR="$(cat /opt/pipeline/.repo_subdir || true)"; if [ -n "$SUBDIR" ]; then WORK_DIR="/opt/pipeline/$SUBDIR"; fi; fi; cd "$WORK_DIR" && if docker compose version >/dev/null 2>&1; then docker compose -f docker-compose.cloud.yml --env-file "$WORK_DIR/.env.cloud" down; else docker-compose -f docker-compose.cloud.yml --env-file "$WORK_DIR/.env.cloud" down; fi'

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

echo -n "$REPO_SUBDIR" > "$APP_DIR/.repo_subdir"
systemctl enable --now pipeline.service
EOF
}
