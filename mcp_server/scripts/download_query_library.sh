#!/bin/bash
# Download OHDSI QueryLibrary query markdown files
# Source: https://github.com/OHDSI/QueryLibrary (Apache 2.0)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/../data/query_library"
REPO_URL="https://github.com/OHDSI/QueryLibrary"
BRANCH="master"

echo "=== OHDSI QueryLibrary Data Download ==="
echo "Target: ${DATA_DIR}"

mkdir -p "${DATA_DIR}"

# Use git sparse checkout to download only the query markdown files
TMPDIR_CLONE=$(mktemp -d)
trap "rm -rf ${TMPDIR_CLONE}" EXIT

cd "${TMPDIR_CLONE}"
git init -q
git remote add origin "${REPO_URL}.git"
git config core.sparseCheckout true
echo "inst/shinyApps/QueryLibrary/queries/" > .git/info/sparse-checkout
git pull -q origin "${BRANCH}" --depth=1

# Copy query directories preserving structure
QUERIES_SRC="${TMPDIR_CLONE}/inst/shinyApps/QueryLibrary/queries"
if [ -d "${QUERIES_SRC}" ]; then
    cp -r "${QUERIES_SRC}/"* "${DATA_DIR}/"
    MD_COUNT=$(find "${DATA_DIR}" -name "*.md" | wc -l | tr -d ' ')
    DIR_COUNT=$(find "${DATA_DIR}" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
    echo "  -> ${MD_COUNT} query files across ${DIR_COUNT} categories"
else
    echo "ERROR: Query files not found at expected path in repository"
    exit 1
fi

echo ""
echo "Download complete!"
echo "  Query files: ${DATA_DIR}/**/*.md"
echo "  Total files: ${MD_COUNT}"
echo "  Categories: ${DIR_COUNT}"
