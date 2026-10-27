#!/usr/bin/env bash
# Rebuilds repro/data from public sources. Usage: repro/run.sh <work_dir>
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
data="$here/data"
get() { [ -s "$2" ] || curl -sS -L --fail --max-time 900 -A "Mozilla/5.0" -o "$2" "$1"; }

get https://www.cms.gov/files/zip/cy2027-landscape-202610.zip "$work/landscape.zip"
get https://www.cms.gov/files/zip/pbp-benefits-2027.zip "$work/pbp.zip"
unzip -oq "$work/landscape.zip" -d "$work"
unzip -oq "$work/pbp.zip" -d "$work/pbp"

py() { python3 -I "$here/scripts/$1" "${@:2}"; }
py universe.py "$work"/CY2027_Landscape_202610/CY2027_Landscape_202610.csv "$data/plans.csv"
py fetch_docs.py "$data/documents.csv" "$data/plans.csv" "$here/../SOURCES_MANIFEST.json" "$work/docs" "$data/documents_checked.csv"
py cite.py "$data/sb_facts.csv" "$data/documents_checked.csv" "$work/docs/text" "$data/citations.csv"
py main_chart.py "$data/plans.csv" "$work/pbp" "$data/citations.csv" "$data/main_chart.csv" "$data/pbp_vs_documents.csv"
py dvha.py "$data/plans.csv" "$work/pbp" "$data/citations.csv" "$data/dvha.csv" "$data/pbp_vs_documents_dvha.csv"
python3 -I "$here/tests/make_fixture.py" "$work/pbp"
python3 -I -m unittest discover -s "$here/tests"
