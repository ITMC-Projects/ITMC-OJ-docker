#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
P="$ROOT/dmoj/production"
TASK=${1:-prod-check}
SERVICE=${2:-}
BACKUP=${3:-}
trap 'echo "Production action failed at line $LINENO ($TASK). Review the error above." >&2' ERR
die() { echo "ERROR: $*" >&2; exit 1; }
dc() {
  docker compose --project-name itmc-oj-prod --env-file "$P/env/prod.env" --project-directory "$ROOT/dmoj" -f "$ROOT/dmoj/docker-compose.yml" -f "$ROOT/dmoj/docker-compose.prod.yml" "$@"
}
init() {
  mkdir -p "$P/env" "$P/data/"{media,problems,backups}
  local name key file secret
  for name in site mysql mysql-admin prod; do
    file="$P/env/$name.env"
    [[ -e "$file" ]] || cp "$file.example" "$file"
    chmod 600 "$file"
  done
  for key in SECRET_KEY MYSQL_PASSWORD MYSQL_ROOT_PASSWORD OTS_SYNC_SERVICE_TOKEN; do
    case "$key" in
      MYSQL_PASSWORD) file="$P/env/mysql.env";;
      MYSQL_ROOT_PASSWORD) file="$P/env/mysql-admin.env";;
      *) file="$P/env/site.env";;
    esac
    # Fill only absent/empty entries, preserve every existing nonempty secret.
    if ! grep -qE "^${key}=.+" "$file"; then
      secret=$(openssl rand -hex 64)
      if grep -q "^${key}=" "$file"; then
        sed -i "s/^${key}=.*/${key}=${secret}/" "$file"
      else
        printf '\n%s=%s\n' "$key" "$secret" >> "$file"
      fi
    fi
  done
  # Nginx must traverse/read public media while backups and env remain private.
  chmod 755 "$P/data" "$P/data/media"
  echo 'Initialized missing environment files. Set domains and OTS endpoint; share the generated OTS token with OTS before deploying.'
}
validate() {
  command -v docker >/dev/null || die 'Docker is required'
  command -v python3 >/dev/null || die 'Python 3 is required for validation'
  python3 "$P/validate.py" "$P"
  [[ -f dmoj/repo/manage.py ]] || die 'Initialize source: git submodule update --init --recursive'
  [[ -f "$P/bootstrap.py" ]] || die 'Missing production/bootstrap.py; update the complete deployment checkout'
  dc config --quiet
}
infra() { dc up -d --wait --wait-timeout 240 db redis; }
build() { dc build base; dc build site celery bridged wsevent; }
migrate() { infra; dc run --rm --no-deps --entrypoint python3 site manage.py migrate --noinput; }
bootstrap() {
  dc run --rm --no-deps --volume "$P/bootstrap.py:/production-bootstrap.py:ro" \
    --entrypoint python3 site /production-bootstrap.py "$@"
}
static() {
  # Source is read-only. Build translations/CSS in a throwaway copy, never in submodule.
  dc run --rm --no-deps --entrypoint bash site -c 'set -e; mkdir /tmp/site; cp -a /site/. /tmp/site/; cd /tmp/site; sed -i "s/\r$//" make_style.sh; bash make_style.sh; python3 manage.py collectstatic --noinput; python3 manage.py compilemessages; python3 manage.py compilejsi18n; cp -r resources /assets/; cp 502.html logo.png robots.txt /assets/'
}
up() { dc up -d --no-build --force-recreate --wait --wait-timeout 240 site celery beat bridged wsevent nginx; }
check() {
  bootstrap --check
  dc run --rm --no-deps --entrypoint python3 site manage.py check --deploy --fail-level WARNING
  dc exec -T nginx nginx -t
  dc exec -T site python3 manage.py migrate --check
  dc ps
}
backup() {
  local stamp stage archive
  stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
  stage=$(mktemp -d "$P/data/backups/.backup.XXXXXX")
  archive="$P/data/backups/oj-$stamp.tar.gz"
  # Quiesce all writers so SQL and filesystem data form a consistent snapshot.
  dc stop nginx site celery beat bridged wsevent
  dc exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb-dump -uroot --single-transaction --add-drop-database --routines --events --triggers --hex-blob --databases "$MYSQL_DATABASE"' > "$stage/database.sql"
  tar -C "$P/data" -czf "$stage/files.tar.gz" media problems
  printf 'ITMC-OJ-BACKUP-v1\n' > "$stage/FORMAT"
  tar -C "$stage" -czf "$archive.partial" FORMAT database.sql files.tar.gz
  mv "$archive.partial" "$archive"
  rm -f "$stage/FORMAT" "$stage/database.sql" "$stage/files.tar.gz"; rmdir "$stage"
  up
  echo "Backup: $archive"
}
restore() {
  [[ -f "$BACKUP" ]] || die 'Specify BACKUP=/absolute/path/to/oj-timestamp.tar.gz'
  python3 "$P/validate.py" --archive "$BACKUP"
  local answer stage
  read -r -p 'Restore replaces database, media and problems. Type RESTORE: ' answer
  [[ "$answer" == RESTORE ]] || die 'Restore cancelled'
  stage=$(mktemp -d "$P/data/backups/.restore.XXXXXX")
  tar -xzf "$BACKUP" -C "$stage"
  dc stop nginx site celery beat bridged wsevent
  infra
  dc exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot' < "$stage/database.sql"
  # Targets are fixed paths below production/data; preserve previous files for recovery.
  local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
  mv "$P/data/media" "$P/data/backups/media-before-$stamp"
  mv "$P/data/problems" "$P/data/backups/problems-before-$stamp"
  tar -xzf "$stage/files.tar.gz" -C "$P/data"
  rm -f "$stage/FORMAT" "$stage/database.sql" "$stage/files.tar.gz"; rmdir "$stage"
  echo 'Restored. Services remain stopped: deploy matching code with make prod (migrations), or make prod-up for an exact-version recovery.'
}
if [[ "$TASK" == prod-init ]]; then init; exit; fi
validate
case "$TASK" in
  prod) build; migrate; bootstrap; static; up; check;;
  prod-build) build;;
  prod-up|prod-restart) up;;
  prod-down) dc down;;
  prod-logs) if [[ -n "$SERVICE" ]]; then dc logs -f --tail 100 "$SERVICE"; else dc logs -f --tail 100; fi;;
  prod-ps) dc ps;;
  prod-migrate) migrate;;
  prod-static) static;;
  prod-check) check;;
  prod-backup) backup;;
  prod-restore) restore;;
  *) die "Unknown action: $TASK";;
esac
