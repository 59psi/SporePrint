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

# v3.4: README.md "**Version:**" banner (if present) + narrow v${CURRENT}
# references that describe the current build. Historical release callouts in
# the README (the > ## v3.3.1 — ... blocks) are intentionally left alone.
if [ -f README.md ]; then
  sed -i.bak "s/^\\*\\*Version:\\*\\* ${ESCAPED}$/\\*\\*Version:\\*\\* ${NEW}/" README.md
fi

# CHANGELOG skeleton insertion — matches the cloud-side bump.sh contract.
CHANGELOG="CHANGELOG.md"
if [ -f "$CHANGELOG" ]; then
  if grep -qE "^## \[$NEW\]" "$CHANGELOG"; then
    echo "✓ CHANGELOG already has an entry for $NEW — leaving it alone"
  else
    DATE="$(date +%Y-%m-%d)"
    INSERT_LINE=$(grep -n '^## \[' "$CHANGELOG" | head -1 | cut -d: -f1 || echo "")
    TEMPLATE="## [$NEW] - $DATE

### Added
- TODO: fill in or delete

### Changed
- TODO: fill in or delete

### Fixed
- TODO: fill in or delete

"
    if [ -n "$INSERT_LINE" ]; then
      CHANGELOG_TEMPLATE="$TEMPLATE" python3 - "$CHANGELOG" "$INSERT_LINE" <<'PYEOF'
import os, sys
path, lineno = sys.argv[1], int(sys.argv[2])
template = os.environ["CHANGELOG_TEMPLATE"]
with open(path) as f:
    lines = f.readlines()
lines.insert(lineno - 1, template)
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
      echo "✓ CHANGELOG skeleton inserted for $NEW — fill in TODOs before committing"
    else
      printf "\n%s" "$TEMPLATE" >> "$CHANGELOG"
      echo "✓ CHANGELOG skeleton appended for $NEW — fill in TODOs before committing"
    fi
  fi
fi

# Doc-drift warning — catches stale "v${CURRENT}" references in README / docs
# that describe current state. Historical release notes in CHANGELOG.md are
# intentionally left alone.
if grep -rn --include='*.md' "v${ESCAPED}\b\|version.*${ESCAPED}\b\|(${ESCAPED})" \
     README.md docs/ 2>/dev/null | grep -vE "CHANGELOG\.md" | head -5; then
  echo "⚠ Found references to old version $CURRENT in Pi docs (sample above). Review any that describe *current* state."
fi

# Clean up .bak files
find . -name "*.bak" -delete 2>/dev/null || true

echo "✓ Version bumped to $NEW"
