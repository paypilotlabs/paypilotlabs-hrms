#!/usr/bin/env bash
# Build the PayPilotLabs HRMS image with frappe_docker's custom Containerfile (Frappe v16: Python 3.14, Node 24).
# Needs: docker, git, and a GitHub token with read access to the private paypilotlabs repos.
# The token is stored in the image build args: use a short-lived read-only token and never push the image.
#   GITHUB_TOKEN=ghp_xxx ./docker/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GITHUB_TOKEN:?set GITHUB_TOKEN to a token that can read github.com/paypilotlabs}"
[ -d .frappe_docker ] || git clone --depth 1 https://github.com/frappe/frappe_docker .frappe_docker
APPS_JSON=$(sed "s#https://github.com/#https://${GITHUB_TOKEN}@github.com/#" docker/apps.json)
docker build \
  --build-arg=FRAPPE_PATH="https://${GITHUB_TOKEN}@github.com/paypilotlabs/paypilotlabs-framework.git" \
  --build-arg=FRAPPE_BRANCH=main \
  --build-arg=PYTHON_VERSION=3.14 \
  --build-arg=NODE_VERSION=24 \
  --build-arg=APPS_JSON_BASE64="$(printf '%s' "$APPS_JSON" | base64 | tr -d '\n')" \
  --tag="${IMAGE:-paypilotlabs/hrms}:${TAG:-latest}" \
  --file=.frappe_docker/images/custom/Containerfile \
  .frappe_docker
