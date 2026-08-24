#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${KAXI_PROJECT_DIR:-/opt/kaxi-erp}"
environment_file="${KAXI_ENVIRONMENT_FILE:-${project_dir}/.env.deploy}"
compose_file="${project_dir}/compose.deploy.yaml"
backup_file="${1:-}"
restore_database="kaxi_erp_restore_check"

[[ -n "${backup_file}" ]] || {
  printf 'Usage: %s /absolute/path/to/kaxi_erp_TIMESTAMP.dump\n' "$0" >&2
  exit 2
}
[[ -f "${backup_file}" ]] || { printf 'Backup not found: %s\n' "${backup_file}" >&2; exit 1; }
[[ -f "${backup_file}.sha256" ]] || {
  printf 'Checksum file not found: %s.sha256\n' "${backup_file}" >&2
  exit 1
}
[[ -f "${environment_file}" ]] || {
  printf 'Environment file not found: %s\n' "${environment_file}" >&2
  exit 1
}

sha256sum --check "${backup_file}.sha256"
compose=(docker compose --env-file "${environment_file}" -f "${compose_file}")

drop_restore_database() {
  "${compose[@]}" exec -T postgres sh -ceu \
    'PGPASSWORD="$POSTGRES_PASSWORD" dropdb --username "$POSTGRES_USER" --if-exists kaxi_erp_restore_check' \
    >/dev/null 2>&1 || true
}
trap drop_restore_database EXIT

drop_restore_database
"${compose[@]}" exec -T postgres sh -ceu \
  'PGPASSWORD="$POSTGRES_PASSWORD" createdb --username "$POSTGRES_USER" kaxi_erp_restore_check'

"${compose[@]}" exec -T postgres sh -ceu \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --username "$POSTGRES_USER" --dbname kaxi_erp_restore_check --no-owner --no-acl --exit-on-error' \
  < "${backup_file}"

verification="$("${compose[@]}" exec -T postgres sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD" psql --username "$POSTGRES_USER" --dbname kaxi_erp_restore_check --tuples-only --no-align --set ON_ERROR_STOP=1 --command "
    SELECT CASE
      WHEN to_regclass('"'"'public.django_migrations'"'"') IS NOT NULL
       AND to_regclass('"'"'public.sys_company'"'"') IS NOT NULL
       AND to_regclass('"'"'public.sys_user'"'"') IS NOT NULL
       AND to_regclass('"'"'public.inv_balance'"'"') IS NOT NULL
       AND to_regclass('"'"'public.fin_journal_entry'"'"') IS NOT NULL
      THEN '"'"'RESTORE_OK'"'"' ELSE '"'"'RESTORE_INCOMPLETE'"'"' END;
  "
')"

[[ "${verification}" == *"RESTORE_OK"* ]] || {
  printf 'Restore verification failed: %s\n' "${verification}" >&2
  exit 1
}

printf 'PostgreSQL restore drill passed in isolated database %s; it will now be removed.\n' "${restore_database}"
