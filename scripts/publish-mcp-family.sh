#!/usr/bin/env bash
# Publish missing *-mcp PyPI project names (new-project create).
# PyPI currently allows ~4 new projects / day / account — stop on 429, do not hammer.
set -euo pipefail

LOG="${PUBLISH_MCP_LOG:-$HOME/dev/imsg-mcp/scripts/publish-mcp-family.log}"
TOKEN="${UV_PUBLISH_TOKEN:-$(python3 -c "import configparser;c=configparser.ConfigParser();c.read('$HOME/.pypirc');print(c['pypi']['password'])")}"
export UV_PUBLISH_TOKEN="$TOKEN"

# name|dir
PACKAGES=(
  "imail-mcp|$HOME/dev/imail-mcp"
  "inotes-mcp|$HOME/dev/inotes-mcp"
  "imsg-mcp|$HOME/dev/imsg-mcp"
  "wa-mcp|$HOME/dev/whatsapp-mcp/wa-mcp"
)

ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

pypi_exists() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://pypi.org/pypi/$1/json")
  [[ "$code" == "200" ]]
}

published=0
failed=0

log "START publish-mcp-family (max new creates this run: ${MAX_NEW:-4})"

for entry in "${PACKAGES[@]}"; do
  name="${entry%%|*}"
  dir="${entry#*|}"
  if pypi_exists "$name"; then
    log "SKIP $name already on PyPI"
    continue
  fi
  if (( published >= ${MAX_NEW:-4} )); then
    log "STOP hit MAX_NEW=${MAX_NEW:-4} — remaining names deferred"
    break
  fi
  log "PUBLISH $name from $dir"
  if (
    cd "$dir"
    rm -rf dist
    uv build
    # Capture publish output — 429 must abort the whole run
    out=$(uv publish 2>&1) || {
      echo "$out"
      if echo "$out" | grep -qi 'Too many new projects'; then
        log "RATE_LIMIT 429 on $name — stop for 24h (do not retry today)"
        exit 42
      fi
      log "FAIL $name"
      exit 1
    }
    echo "$out"
  ); then
    log "OK $name"
    published=$((published + 1))
    # gentle spacing between creates
    sleep "${SLEEP_BETWEEN:-30}"
  else
    rc=$?
    failed=$((failed + 1))
    if [[ $rc -eq 42 ]]; then
      log "DONE early due to rate limit. published=$published"
      exit 42
    fi
    log "FAIL $name rc=$rc"
  fi
done

log "DONE published=$published failed=$failed"
# success if every target name now exists
missing=0
for entry in "${PACKAGES[@]}"; do
  name="${entry%%|*}"
  pypi_exists "$name" || missing=$((missing + 1))
done
if (( missing == 0 )); then
  log "ALL_TARGET_NAMES_LIVE"
  exit 0
fi
log "STILL_MISSING=$missing"
exit 1
