#!/usr/bin/env bash
set -Eeuo pipefail

repository="${KAXI_GITHUB_REPOSITORY:-KaXiTreasure/KaXiERP}"
release_tag="${KAXI_RELEASE_TAG:-latest}"
project_dir="${KAXI_PROJECT_DIR:-/vol1/docker/kaxi-erp}"
http_port_requested="${KAXI_HTTP_PORT:-8088}"
bundle_name="kaxi-erp-deploy.zip"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ "${release_tag}" == "latest" ]]; then
  release_base="https://github.com/${repository}/releases/latest/download"
else
  [[ "${release_tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "KAXI_RELEASE_TAG must use vMAJOR.MINOR.PATCH format"
  release_base="https://github.com/${repository}/releases/download/${release_tag}"
fi

if [[ "$(id -u)" -ne 0 ]]; then
  fail "Please run with sudo: curl -fsSL https://raw.githubusercontent.com/${repository}/main/scripts/install-fnos.sh | sudo bash"
fi

for command_name in curl unzip sha256sum openssl awk grep mktemp docker; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "Missing command: ${command_name}"
done
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"

temporary_dir="$(mktemp -d /tmp/kaxi-fnos-install.XXXXXX)"
trap 'rm -rf "${temporary_dir}"' EXIT

printf 'Downloading the latest verified KAXI ERP release...\n'
curl -fL --retry 3 --connect-timeout 20 \
  "${release_base}/${bundle_name}" \
  -o "${temporary_dir}/${bundle_name}" \
  || fail "Release download failed. Confirm that the GitHub repository is public and has a successful release."
curl -fL --retry 3 --connect-timeout 20 \
  "${release_base}/${bundle_name}.sha256" \
  -o "${temporary_dir}/${bundle_name}.sha256" \
  || fail "Release checksum download failed"

(
  cd "${temporary_dir}"
  sha256sum -c "${bundle_name}.sha256"
) || fail "Deployment bundle SHA-256 verification failed"

unzip -q "${temporary_dir}/${bundle_name}" -d "${temporary_dir}/unpacked"
bundle_dir="$(find "${temporary_dir}/unpacked" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[[ -n "${bundle_dir}" && -f "${bundle_dir}/compose.deploy.yaml" ]] || fail "Invalid deployment bundle structure"

existing_install=false
if [[ -f "${project_dir}/.env" ]]; then
  existing_install=true
fi

if [[ "${existing_install}" == false ]]; then
  if command -v ss >/dev/null 2>&1 && ss -H -ltn 2>/dev/null | awk -v port=":${http_port_requested}" '$4 ~ port "$" {found=1} END {exit !found}'; then
    fail "Port ${http_port_requested} is already in use. Set KAXI_HTTP_PORT to a free port before installing."
  fi
fi

mkdir -p "${project_dir}"
cp -a "${bundle_dir}/." "${project_dir}/"
chmod +x "${project_dir}"/scripts/*.sh

environment_file="${project_dir}/.env"
if [[ "${existing_install}" == false ]]; then
  cp "${project_dir}/.env.deploy.example" "${environment_file}"
  chmod 600 "${environment_file}"
fi

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
  chmod 600 "${temporary_file}"
  mv -f "${temporary_file}" "${environment_file}"
}

if [[ "${existing_install}" == false ]]; then
  update_environment_value KAXI_ENV_FILE .env
  update_environment_value KAXI_SECRET_KEY "$(openssl rand -hex 32)"
  update_environment_value KAXI_ALLOWED_HOSTS '*'
  update_environment_value KAXI_HTTPS_ENABLED false
  update_environment_value KAXI_DB_PASSWORD "$(openssl rand -hex 24)"
  update_environment_value KAXI_S3_ACCESS_KEY kaxi_minio
  update_environment_value KAXI_S3_SECRET_KEY "$(openssl rand -hex 24)"
  update_environment_value KAXI_HTTP_PORT "${http_port_requested}"
fi

printf 'Starting KAXI ERP with immutable image digests...\n'
KAXI_PROJECT_DIR="${project_dir}" \
  "${project_dir}/scripts/deploy-linux.sh" \
  "${environment_file}" \
  "${project_dir}/release-images.env" \
  "${project_dir}/release-images.env.sha256"

http_port="$(awk -F= '$1 == "KAXI_HTTP_PORT" {print $2}' "${environment_file}" | tail -n 1)"
[[ -n "${http_port}" ]] || http_port=8088

printf '\nKAXI ERP deployment completed.\n'
printf 'Open: http://<current-fnOS-IP>:%s\n' "${http_port}"
printf 'Initial username: admin\n'
printf 'Initial password: 12345678\n'
printf 'You must change the password after the first login.\n'
printf 'Configuration: %s\n' "${environment_file}"
