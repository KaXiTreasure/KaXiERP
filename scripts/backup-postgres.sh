#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${KAXI_PROJECT_DIR:-/opt/kaxi-erp}"
environment_file="${1:-${project_dir}/.env.deploy}"
compose_file="${project_dir}/compose.deploy.yaml"
backup_dir="${KAXI_BACKUP_DIR:-${project_dir}/backups/postgres}"
retention_days="${KAXI_BACKUP_RETENTION_DAYS:-30}"

[[ -f "${environment_file}" ]] || { printf 'Missing environment file: %s\n' "${environment_file}" >&2; exit 1; }
mkdir -p "${backup_dir}"
chmod 700 "${backup_dir}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${backup_dir}/kaxi_erp_${timestamp}.dump"
temporary_file="${backup_file}.partial"
compose=(docker compose --env-file "${environment_file}" -f "${compose_file}")

cleanup() { rm -f "${temporary_file}"; }
trap cleanup EXIT

"${compose[@]}" exec -T postgres sh -ceu \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "${temporary_file}"
[[ -s "${temporary_file}" ]] || { printf 'PostgreSQL backup is empty\n' >&2; exit 1; }
mv "${temporary_file}" "${backup_file}"
sha256sum "${backup_file}" > "${backup_file}.sha256"
find "${backup_dir}" -type f -mtime "+${retention_days}" \( -name '*.dump' -o -name '*.dump.sha256' \) -delete
printf 'PostgreSQL backup created: %s\n' "${backup_file}"
