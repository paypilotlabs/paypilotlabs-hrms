#!/usr/bin/env bash
# Build the PayPilotLabs HRMS image with the custom Containerfile from paypilotlabs-docker
# (a fork of frappe/frappe_docker, MIT). Frappe v16: Python 3.14, Node 24.
# Needs: docker with BuildKit, and git. Public repos need no token:
#   ./docker/build.sh
# Private repos need a GitHub token with read access:
#   GITHUB_TOKEN=ghp_xxx ./docker/build.sh
# Tags: $IMAGE:<git commit> (push this one to ECR; "-dirty" means uncommitted changes) and
# $IMAGE:latest (what docker/docker-compose.yml runs).
# Overrides: IMAGE, TAG, FRAPPE_BRANCH, DOCKER_REF (paypilotlabs-docker branch), APPS_JSON.
# apps.json goes in as a BuildKit secret (not stored in the image). The framework URL is a build
# arg, so with a token set that token ends up in the image history (docker history): keep such an
# image local.
# Secrets are not part of BuildKit's cache key, so CACHE_BUST carries a hash of apps.json; without it
# a cached bench layer built from another product's apps.json would be reused.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-paypilotlabshrms}
TAG=${TAG:-$(git describe --always --dirty --exclude='*')}
AUTH=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH="${GITHUB_TOKEN}@"
  echo "warning: GITHUB_TOKEN is stored in this image's build history; keep the image local." >&2
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git clone -q --depth 1 --branch "${DOCKER_REF:-main}" https://github.com/paypilotlabs/paypilotlabs-docker.git "$WORK/docker"
sed "s#https://github.com/#https://${AUTH}github.com/#" "${APPS_JSON:-docker/apps.json}" > "$WORK/apps.json"
DOCKER_BUILDKIT=1 docker build \
  --build-arg=FRAPPE_PATH="https://${AUTH}github.com/paypilotlabs/paypilotlabs-framework.git" \
  --build-arg=FRAPPE_BRANCH="${FRAPPE_BRANCH:-develop}" \
  --build-arg=PYTHON_VERSION=3.14 \
  --build-arg=NODE_VERSION=24 \
  --build-arg=CACHE_BUST="$(shasum -a 256 "$WORK/apps.json" | cut -d' ' -f1)" \
  --secret=id=apps_json,src="$WORK/apps.json" \
  --tag="$IMAGE:$TAG" \
  --tag="$IMAGE:latest" \
  --file="$WORK/docker/images/custom/Containerfile" \
  "$WORK/docker"
echo "Built $IMAGE:$TAG (also tagged $IMAGE:latest)"
