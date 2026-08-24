#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${KAXI_PROJECT_DIR:-/opt/kaxi-erp}"
environment_file="${1:-${project_dir}/.env.deploy}"
release_manifest="${2:-${project_dir}/release-images.env}"
checksum_file="${3:-${release_manifest}.sha256}"
compose_file="${project_dir}/compose.deploy.yaml"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for command_name in docker sha256sum awk grep mktemp; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "Missing command: ${command_name}"
done

for required_file in "${environment_file}" "${release_manifest}" "${checksum_file}" "${compose_file}"; do
  [[ -f "${required_file}" ]] || fail "Missing file: ${required_file}"
done

expected_checksum="$(awk 'NR == 1 {print toupper($1)}' "${checksum_file}")"
actual_checksum="$(sha256sum "${release_manifest}" | awk '{print toupper($1)}')"
[[ "${expected_checksum}" =~ ^[A-F0-9]{64}$ ]] || fail "Invalid release manifest checksum"
[[ "${actual_checksum}" == "${expected_checksum}" ]] || fail "Release manifest checksum mismatch"

read_manifest_value() {
  local name="$1"
  local value
  value="$(grep -E "^${name}=" "${release_manifest}" | tail -n 1 | cut -d= -f2-)"
  [[ "${value}" =~ ^[^[:space:]@]+@sha256:[a-fA-F0-9]{64}$ ]] || fail "${name} is not an immutable image reference"
  printf '%s' "${value}"
}

update_environment_value() {
  local name="$1"
  local value="$2"
  local temporary_file
  temporary_file="$(mktemp "${environment_file}.XXXXXX")"
  awk -v key="${name}" -v replacement="${value}" '
    BEGIN { found = 0 }
    $0 ~ "^" key "=" { print key "=" replacement; found = 1; next }
    { print }
    END { if (!found) print key "=" replacement }
  ' "${environment_file}" > "${temporary_file}"
  chmod --reference="${environment_file}" "${temporary_file}"
  mv -f "${temporary_file}" "${environment_file}"
}

image_variables=(
  KAXI_BACKEND_IMAGE
  KAXI_WEB_IMAGE
  KAXI_POSTGRES_IMAGE
  KAXI_REDIS_IMAGE
  KAXI_MINIO_IMAGE
  KAXI_MINIO_CLIENT_IMAGE
)
for image_variable in "${image_variables[@]}"; do
  update_environment_value "${image_variable}" "$(read_manifest_value "${image_variable}")"
done

compose=(docker compose --env-file "${environment_file}" -f "${compose_file}")
"${compose[@]}" config --quiet

if "${compose[@]}" ps --status running --services | grep -qx postgres; then
  "${project_dir}/scripts/backup-postgres.sh" "${environment_file}"
fi

"${compose[@]}" pull
"${compose[@]}" up -d --remove-orphans

for attempt in $(seq 1 60); do
  migrate_id="$("${compose[@]}" ps -aq migrate 2>/dev/null || true)"
  backend_id="$("${compose[@]}" ps -q backend 2>/dev/null || true)"
  web_id="$("${compose[@]}" ps -q web 2>/dev/null || true)"
  migrate_status="$(docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "${migrate_id}" 2>/dev/null || true)"
  backend_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${backend_id}" 2>/dev/null || true)"
  web_status="$(docker inspect --format '{{.State.Status}}' "${web_id}" 2>/dev/null || true)"
  if [[ "${migrate_status}" == "exited:0" && "${backend_health}" == "healthy" && "${web_status}" == "running" ]]; then
    printf 'Deployment completed with verified migration and healthy backend.\n'
    exit 0
  fi
  sleep 5
done

"${compose[@]}" ps -a >&2
"${compose[@]}" logs --tail 100 migrate backend web >&2
fail "Deployment did not become healthy within 300 seconds"
