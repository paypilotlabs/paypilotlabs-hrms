#!/usr/bin/env bash
# Build the PayPilotLabs HRMS image with frappe_docker's custom Containerfile (Frappe v16: Python 3.14, Node 24).
# Needs: docker with BuildKit, and git. Public repos need no token:
#   ./docker/build.sh
# Private repos need a GitHub token with read access:
#   GITHUB_TOKEN=ghp_xxx ./docker/build.sh
# apps.json goes in as a BuildKit secret (not stored in the image). The framework URL is a build
# arg, so with a token set that token ends up in the image history (docker history): keep such an
# image local. Override the framework branch with FRAPPE_BRANCH.
# Secrets are not part of BuildKit's cache key, so CACHE_BUST carries a hash of apps.json; without it
# a cached bench layer built from another product's apps.json would be reused.
# OPENSSL_armcap=0 goes into the image (build and runtime): cryptography>=48 bundles an OpenSSL whose
# CPU probe dies with SIGILL on Apple M4 under Docker's Linux VM. It only skips ARM crypto speedups.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .frappe_docker ] || git clone --depth 1 https://github.com/frappe/frappe_docker .frappe_docker
AUTH=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH="${GITHUB_TOKEN}@"
  echo "warning: GITHUB_TOKEN is stored in this image's build history; keep the image local." >&2
fi
APPS_JSON_FILE=$(mktemp)
CONTAINERFILE=$(mktemp)
trap 'rm -f "$APPS_JSON_FILE" "$CONTAINERFILE"' EXIT
awk '{print} / AS base$/{print "ENV OPENSSL_armcap=0"}' .frappe_docker/images/custom/Containerfile > "$CONTAINERFILE"
grep -q '^ENV OPENSSL_armcap=0' "$CONTAINERFILE" || { echo "error: no 'AS base' stage in the Containerfile" >&2; exit 1; }
sed "s#https://github.com/#https://${AUTH}github.com/#" "${APPS_JSON:-docker/apps.json}" > "$APPS_JSON_FILE"
DOCKER_BUILDKIT=1 docker build \
  --build-arg=FRAPPE_PATH="https://${AUTH}github.com/paypilotlabs/paypilotlabs-framework.git" \
  --build-arg=FRAPPE_BRANCH="${FRAPPE_BRANCH:-develop}" \
  --build-arg=PYTHON_VERSION=3.14 \
  --build-arg=NODE_VERSION=24 \
  --build-arg=CACHE_BUST="$(shasum -a 256 "$APPS_JSON_FILE" | cut -d' ' -f1)" \
  --secret=id=apps_json,src="$APPS_JSON_FILE" \
  --tag="${IMAGE:-paypilotlabs/hrms}:${TAG:-latest}" \
  --file="$CONTAINERFILE" \
  .frappe_docker
