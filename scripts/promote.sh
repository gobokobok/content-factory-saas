#!/usr/bin/env bash
# Promote DEV to PROD by creating a git tag.
# Usage: bash scripts/promote.sh v1.0.0

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: bash scripts/promote.sh <version>"
  echo "Example: bash scripts/promote.sh v1.2.0"
  exit 1
fi

version="$1"

# Validate semver tag format
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: version must be in format v<major>.<minor>.<patch> (e.g. v1.0.0)"
  exit 1
fi

# Ensure we're on main and up to date
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" != "main" ]; then
  echo "ERROR: must be on main branch to promote. Currently on: $current_branch"
  exit 1
fi

git fetch origin main --quiet
local_hash=$(git rev-parse HEAD)
remote_hash=$(git rev-parse origin/main)
if [ "$local_hash" != "$remote_hash" ]; then
  echo "ERROR: local main is not up to date with origin/main. Pull first."
  exit 1
fi

echo "→ Tagging $version on main ($(git rev-parse --short HEAD))"
git tag "$version"
git push origin "$version"

echo "✓ Tag $version pushed. GitHub Actions CD workflow will deploy to PROD."
echo "  Monitor: https://github.com/<your-repo>/actions"
