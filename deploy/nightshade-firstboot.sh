#!/bin/bash
# Nightshade / Kali first-boot provisioning.
#
# Offline-friendly: every apt dependency (python3-spidev, python3-rpi.gpio,
# python3-gpiozero, python3-colorzero, fonts-dejavu-*, tailscale) is already
# baked into the image, so no network is required to get the panel up.
#
# The display must never wait on the network. The previous revision pinged the
# internet for up to 60s and ran `tailscale up` with a 60s timeout before it
# refreshed the app, so every boot sat on a black panel for minutes. Everything
# the panel needs is done first; the Tailscale bring-up runs detached.
exec > /var/log/nightshade-firstboot.log 2>&1
set -x
date -Is
echo "NIGHTSHADE firstboot $(date -Is) kernel=$(uname -r) model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
for d in /boot/firmware /boot; do
    [ -d "$d" ] || continue
    echo "Nightshade firstboot $(date -Is) on $(uname -r)" > "$d/NIGHTSHADE_FIRSTBOOT.txt" 2>/dev/null || true
done

# The provisioning account should already exist on the baked image; wait only
# briefly so a slow cloud-init cannot strand the panel.
for _ in $(seq 1 60); do id kali >/dev/null 2>&1 && break; sleep 1; done

/usr/bin/python3 - <<'PY'
import importlib.util
for module in ('PIL', 'spidev', 'gpiozero', 'colorzero'):
    print(module, 'ok' if importlib.util.find_spec(module) is not None else 'MISSING')
PY

# Refresh Nightshade for the kali user and (re)start the service. This is the
# only part on the boot critical path and it is local disk I/O only.
install -d -o kali -g kali /home/kali
# Swap the tree in atomically. The old code did `rm -rf` then `cp`, so a card
# unplugged mid-copy came back with no application at all; a staged copy plus
# rename means a cut leaves either the old or the new tree, never neither.
rm -rf /home/kali/nightshade.new
cp -a /opt/nightshade /home/kali/nightshade.new
find /home/kali/nightshade.new -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
chown -R kali:kali /home/kali/nightshade.new
sync
rm -rf /home/kali/nightshade.old
if [ -d /home/kali/nightshade ]; then mv /home/kali/nightshade /home/kali/nightshade.old; fi
mv /home/kali/nightshade.new /home/kali/nightshade
sync
install -d -o kali -g kali -m 700 /home/kali/.local/state/nightshade
cp -a /opt/nightshade-state/. /home/kali/.local/state/nightshade/ 2>/dev/null || true
chown -R kali:kali /home/kali/.local
/bin/bash /home/kali/nightshade/deploy/install.sh || true
rm -rf /home/kali/nightshade.old

# Bring Tailscale up in the background. A cold network can take a minute and it
# must never delay the panel: the app listens on 0.0.0.0 and the Tailscale
# address simply appears once the node finishes connecting. setsid detaches it
# from this unit so it survives the oneshot finishing.
if command -v tailscale >/dev/null 2>&1; then
    setsid nohup /bin/sh -c '
        systemctl enable --now tailscaled 2>/dev/null || true
        for _ in $(seq 1 60); do tailscale status >/dev/null 2>&1 && break; sleep 2; done
        timeout 120 tailscale up --accept-routes --hostname=pi 2>/dev/null || true
    ' >/var/log/nightshade-tailscale.log 2>&1 < /dev/null &
fi
exit 0
