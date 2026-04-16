#!/usr/bin/env bash
# scripts/bump.sh — Bump SporePrint version across all files
# Usage: ./scripts/bump.sh [patch|minor|major]
set -euo pipefail

LEVEL="${1:-patch}"

# Read current version from server
CURRENT=$(grep -oE '"[0-9]+\.[0-9]+\.[0-9]+"' server/app/main.py | head -1 | tr -d '"')

if [ -z "$CURRENT" ]; then
  echo "ERROR: Could not read version from server/app/main.py"
  exit 1
fi

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$LEVEL" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
  *) echo "Usage: $0 [patch|minor|major]"; exit 1 ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"
echo "Bumping $CURRENT → $NEW ($LEVEL)"

# Escape dots for sed regex (3.0.10 → 3\.0\.10) to avoid matching unrelated numbers
ESCAPED=$(echo "$CURRENT" | sed 's/\./\\./g')

# Update server version (only match exact version strings, not random numbers)
sed -i.bak "s/\"${ESCAPED}\"/\"${NEW}\"/g" server/app/main.py
sed -i.bak "s/\"${ESCAPED}\"/\"${NEW}\"/g" server/tests/test_api.py

# Update UI version
sed -i.bak "s/\"version\": \"${ESCAPED}\"/\"version\": \"${NEW}\"/" ui/package.json
sed -i.bak "s/v${ESCAPED}/v${NEW}/g" ui/src/components/layout/Sidebar.tsx

# Update pyproject.toml
sed -i.bak "s/version = \"${ESCAPED}\"/version = \"${NEW}\"/" server/pyproject.toml

# Clean up .bak files
find . -name "*.bak" -delete 2>/dev/null || true

echo "✓ Version bumped to $NEW"
