#!/bin/bash
# Download OHDSI PhenotypeLibrary data (Cohorts.csv + cohort JSONs)
# Source: https://github.com/OHDSI/PhenotypeLibrary (Apache 2.0)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/../data/phenotype_library"
REPO_URL="https://github.com/OHDSI/PhenotypeLibrary"
BRANCH="main"

echo "=== OHDSI PhenotypeLibrary Data Download ==="
echo "Target: ${DATA_DIR}"

mkdir -p "${DATA_DIR}/cohorts"

# Download Cohorts.csv (metadata catalog)
echo "Downloading Cohorts.csv..."
curl -sL "${REPO_URL}/raw/${BRANCH}/inst/Cohorts.csv" -o "${DATA_DIR}/Cohorts.csv"
ROW_COUNT=$(tail -n +2 "${DATA_DIR}/Cohorts.csv" | wc -l | tr -d ' ')
echo "  -> ${ROW_COUNT} cohort entries"

# Download all cohort JSON files via GitHub API (list directory, then fetch each)
echo "Downloading cohort JSON files..."
# Use git sparse checkout for efficiency
TMPDIR_CLONE=$(mktemp -d)
trap "rm -rf ${TMPDIR_CLONE}" EXIT

cd "${TMPDIR_CLONE}"
git init -q
git remote add origin "${REPO_URL}.git"
git config core.sparseCheckout true
echo "inst/cohorts/" > .git/info/sparse-checkout
git pull -q origin "${BRANCH}" --depth=1

# Copy JSON files to data directory
cp "${TMPDIR_CLONE}/inst/cohorts/"*.json "${DATA_DIR}/cohorts/"
JSON_COUNT=$(ls "${DATA_DIR}/cohorts/"*.json 2>/dev/null | wc -l | tr -d ' ')
echo "  -> ${JSON_COUNT} cohort JSON files"

echo ""
echo "Download complete!"
echo "  Cohorts.csv: ${DATA_DIR}/Cohorts.csv"
echo "  Cohort JSONs: ${DATA_DIR}/cohorts/*.json"
echo "  Total JSON files: ${JSON_COUNT}"
