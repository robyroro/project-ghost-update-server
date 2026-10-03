#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Provisions Ghost's update server on Debian 12, or brings it back in line.
# tools/deploy.py runs it as root:
#   provision.sh --address <public address> --bundle <unpacked bundle>
# Each step changes only what differs and says so. A second run reports
# "provision: 0 change(s)".
set -euo pipefail

ADDRESS="" BUNDLE=""
while [ $# -gt 0 ]; do
  case $1 in
    --address) ADDRESS=$2; shift 2 ;;
    --bundle) BUNDLE=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ $ADDRESS =~ ^[A-Za-z0-9.-]+$ ]] || { echo "--address is required" >&2; exit 2; }
[ -d "$BUNDLE/deploy" ] || { echo "--bundle is required" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }

CHANGES=0
SERVICE_CHANGED=0
changed() { echo "changed: $*"; CHANGES=$((CHANGES + 1)); }

# install_file SRC DEST MODE [OWNER]: succeeds if it changed DEST.
install_file() {
  local src=$1 dest=$2 mode=$3 owner=${4:-root}
  if [ -f "$dest" ] && cmp -s "$src" "$dest" \
      && [ "$(stat -c '%a %U' "$dest")" = "$mode $owner" ]; then
    return 1
  fi
  install -D -m "$mode" -o "$owner" -g "$owner" "$src" "$dest"
  changed "$dest"
}

# rendered TEMPLATE: prints a temporary file with @ADDRESS@ replaced.
rendered() {
  local tmp
  tmp=$(mktemp)
  sed "s/@ADDRESS@/$ADDRESS/g" "$1" > "$tmp"
  echo "$tmp"
}

# ensure_dir PATH MODE OWNER
ensure_dir() {
  if [ -d "$1" ] && [ "$(stat -c '%a %U' "$1")" = "$2 $3" ]; then return; fi
  install -d -m "$2" -o "$3" -g "$3" "$1"
  changed "$1"
}

# 1. Packages. Debian 12 ships Caddy 2.6 and python3-cryptography 38.
missing=()
for p in caddy curl nftables python3 python3-cryptography sudo unattended-upgrades; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" \
    || missing+=("$p")
done
if [ ${#missing[@]} -gt 0 ]; then
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${missing[@]}"
  changed "packages: ${missing[*]}"
fi
install_file "$BUNDLE/deploy/20auto-upgrades" /etc/apt/apt.conf.d/20auto-upgrades 644 || true

# 2. The administrator: SSH keys only, no root login.
if ! id ghost >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash ghost
  changed "user ghost"
fi
if [ ! -s /home/ghost/.ssh/authorized_keys ]; then
  install -d -m 700 -o ghost -g ghost /home/ghost/.ssh
  install -m 600 -o ghost -g ghost /root/.ssh/authorized_keys /home/ghost/.ssh/authorized_keys
  changed "ghost's SSH keys, copied from root's"
fi
visudo -cf "$BUNDLE/deploy/sudoers" >/dev/null
install_file "$BUNDLE/deploy/sudoers" /etc/sudoers.d/ghost 440 || true
if install_file "$BUNDLE/deploy/sshd.conf" /etc/ssh/sshd_config.d/ghost.conf 644; then
  sshd -t
  systemctl reload ssh
fi

# 3. The service, its configuration and its key.
while IFS= read -r f; do
  if install_file "$BUNDLE/$f" "/opt/ghost-update/$f" 644; then SERVICE_CHANGED=1; fi
done < <(cd "$BUNDLE" && find ghost_update -name '*.py' | sort)
install_file "$BUNDLE/deploy/ghost-update-admin" /usr/local/sbin/ghost-update-admin 755 || true
config=$(rendered "$BUNDLE/deploy/server.json")
if install_file "$config" /etc/ghost-update/server.json 644; then SERVICE_CHANGED=1; fi
rm -f "$config"
if install_file "$BUNDLE/cup_key.json" /etc/ghost-update/cup_key.json 600; then
  SERVICE_CHANGED=1
fi
if install_file "$BUNDLE/deploy/ghost-update.service" /etc/systemd/system/ghost-update.service 644; then
  systemctl daemon-reload
  SERVICE_CHANGED=1
fi
ensure_dir /srv/releases 755 root
ensure_dir /srv/releases/staging 755 ghost
if [ ! -f /srv/releases/releases.json ]; then
  /usr/local/sbin/ghost-update-admin init
  changed /srv/releases/releases.json
fi

# 4. Caddy and the firewall, each checked before it is installed.
caddyfile=$(rendered "$BUNDLE/deploy/Caddyfile")
caddy validate --config "$caddyfile" --adapter caddyfile >/dev/null 2>&1 \
  || { caddy validate --config "$caddyfile" --adapter caddyfile; exit 1; }
if install_file "$caddyfile" /etc/caddy/Caddyfile 644; then systemctl restart caddy; fi
rm -f "$caddyfile"
nft -c -f "$BUNDLE/deploy/nftables.conf"
if install_file "$BUNDLE/deploy/nftables.conf" /etc/nftables.conf 755; then
  systemctl restart nftables
fi

# 5. Enabled and running.
for unit in nftables caddy ghost-update; do
  if ! systemctl is-enabled --quiet "$unit"; then
    systemctl enable --quiet "$unit"
    changed "$unit enabled"
  fi
done
if [ "$SERVICE_CHANGED" = 1 ] || ! systemctl is-active --quiet ghost-update; then
  systemctl restart ghost-update
  changed "ghost-update restarted"
fi
for unit in nftables caddy; do
  if ! systemctl is-active --quiet "$unit"; then
    systemctl start "$unit"
    changed "$unit started"
  fi
done

# 6. Check: through Caddy, the service refuses a request without cup2key.
root_cert=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  [ -f "$root_cert" ] && break
  sleep 1
done
code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$root_cert" -X POST --data '{}' \
  "https://$ADDRESS/update" || true)
if [ "$code" != 400 ]; then
  echo "check failed: POST /update without cup2key answered '$code', expected 400" >&2
  exit 1
fi
echo "provision: $CHANGES change(s)"
