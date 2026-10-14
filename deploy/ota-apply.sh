#!/bin/bash
# Nightshade OTA apply.
#
# Runs as the root nightshade-ota.service unit -- deliberately NOT
# inside the sandboxed nightshade.service: pulling and installing
# means writing to /opt, /etc, /boot and the home tree, which the
# app's systemd sandbox keeps read-only. The Settings menu tool
# (scripts/ota_update.py) starts this unit and tails its log, so
# the panel shows live progress.
set -uo pipefail

REPO=/opt/nightshade
LOG=/home/kali/.local/state/nightshade/ota.log

umask 022
: > "$LOG"

{
  echo "Nightshade OTA apply $(date -Is)"
  PULL=$(git -C "$REPO" pull --ff-only 2>&1)
  echo "$PULL"
  if echo "$PULL" | grep -q 'Already up to date'; then
    echo "Already the newest version"
  else
    echo "Applying to both trees..."
    bash "$REPO/deploy/install.sh"
    echo "Update applied - restarting nightshade"
    # Give the panel a moment to show the final line before
    # the restart takes the running job (and the old code)
    # down with it.
    sleep 3
    systemctl restart nightshade
  fi
  echo __OTA_DONE__
} >> "$LOG" 2>&1
