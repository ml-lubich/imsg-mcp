#!/usr/bin/env bash
# Retry publishing *-mcp / wa-mcp after PyPI new-project rate limit clears.
set -euo pipefail
TOKEN="${UV_PUBLISH_TOKEN:-$(python3 -c "import configparser;c=configparser.ConfigParser();c.read('$HOME/.pypirc');print(c['pypi']['password'])")}"
export UV_PUBLISH_TOKEN="$TOKEN"
for dir in \
  "$HOME/dev/imail" \
  "$HOME/dev/inotes" \
  "$HOME/dev/imsg" \
  "$HOME/dev/whatsapp-mcp/wa-cli" \
  "$HOME/dev/whatsapp-mcp/whatsapp-mcp-server"
do
  echo "==== $dir ===="
  (cd "$dir" && rm -rf dist && uv build && uv publish) || echo "FAIL $dir"
done
