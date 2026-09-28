#!/usr/bin/env bash
# Shared client body for GitLab suite Docker/Podman tests.
# Env: SUITE (focal|jammy|noble), MODE (install|reinstall), REPO_MAN (host:port)
set -euo pipefail

SUITE="${SUITE:?SUITE required}"
MODE="${MODE:-install}"
REPO_MAN="${REPO_MAN:-repo-man:8080}"
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

APT_OPTS=(
  -o Acquire::AllowInsecureRepositories=true
  -o Acquire::AllowDowngradeToInsecureRepositories=true
  -o APT::Get::AllowUnauthenticated=true
  -o Acquire::http::Timeout=3600
  -o Acquire::https::Timeout=3600
  -o Acquire::Retries=5
)

rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
# trusted=yes so unsigned mirror indexes can resolve dependencies (perl, git, …)
# Include -updates/-security so image-preinstalled packages (e.g. perl-base) match installable deps.
cat >/etc/apt/sources.list <<EOF
deb [trusted=yes] http://${REPO_MAN}/ubuntu ${SUITE} main universe
deb [trusted=yes] http://${REPO_MAN}/ubuntu ${SUITE}-updates main universe
deb [trusted=yes] http://${REPO_MAN}/ubuntu ${SUITE}-security main universe
deb [trusted=yes] http://${REPO_MAN}/GitLab/${SUITE} ${SUITE} main
deb [trusted=yes] http://${REPO_MAN}/gitlab-runner/${SUITE} ${SUITE} main
EOF

apt-get update "${APT_OPTS[@]}"

# Official Ubuntu images often lack curl; need it to warm large pool blobs.
if ! command -v curl >/dev/null 2>&1; then
  apt-get install -y --allow-unauthenticated "${APT_OPTS[@]}" curl
fi

if [ "${MODE}" = "reinstall" ]; then
  apt-get remove -y --purge gitlab-ce gitlab-runner 2>/dev/null || true
  apt-get autoremove -y 2>/dev/null || true
fi

# Warm large blobs through the mirror with curl (long timeout) so apt hits cache.
# Otherwise apt may drop the connection while repo-man is still pulling ~1GiB from upstream.
warm_pool_pkg() {
  local pkg="$1" prefix="$2"
  local filename
  # Avoid pipefail+awk-early-exit SIGPIPE (exit 141) when Filename is found.
  filename="$(
    set +o pipefail
    apt-cache show "$pkg" 2>/dev/null | awk '/^Filename:/{print $2; exit}'
  )"
  if [ -z "$filename" ]; then
    echo "WARN: no Filename for $pkg" >&2
    return 0
  fi
  echo "Warming cache: ${prefix}/${filename}"
  curl -fsSL --max-time 3600 -o /dev/null "http://${REPO_MAN}${prefix}/${filename}"
}

warm_pool_pkg gitlab-ce "/GitLab/${SUITE}"
warm_pool_pkg gitlab-runner "/gitlab-runner/${SUITE}"
# helper images package is often pulled as a dependency of gitlab-runner
if apt-cache show gitlab-runner-helper-images >/dev/null 2>&1; then
  warm_pool_pkg gitlab-runner-helper-images "/gitlab-runner/${SUITE}" || true
fi

# Download first so we can fingerprint the exact blobs apt accepted for this suite
apt-get install -y --download-only --allow-unauthenticated "${APT_OPTS[@]}" gitlab-ce gitlab-runner

mkdir -p /tmp/suite-evidence
: >/tmp/suite-evidence/sha256.txt
shopt -s nullglob
for deb in /var/cache/apt/archives/gitlab-ce_*.deb /var/cache/apt/archives/gitlab-runner_*.deb; do
  sha256sum "$deb" >>/tmp/suite-evidence/sha256.txt
done
shopt -u nullglob
test -s /tmp/suite-evidence/sha256.txt

apt-get install -y --allow-unauthenticated "${APT_OPTS[@]}" gitlab-ce gitlab-runner

dpkg -l gitlab-ce gitlab-runner | tee /tmp/suite-evidence/dpkg.txt
dpkg-query -W -f='${Package} ${Version} ${Architecture}\n' gitlab-ce gitlab-runner | tee /tmp/suite-evidence/versions.txt

CE_VER=$(dpkg-query -W -f='${Version}' gitlab-ce)
RUNNER_VER=$(dpkg-query -W -f='${Version}' gitlab-runner)
test -n "$CE_VER"
test -n "$RUNNER_VER"

echo "OK suite=${SUITE} mode=${MODE} gitlab-ce=${CE_VER} gitlab-runner=${RUNNER_VER}"
cat /tmp/suite-evidence/sha256.txt
