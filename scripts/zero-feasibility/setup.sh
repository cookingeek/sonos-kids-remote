#!/usr/bin/env bash
# Richtet einen Raspberry Pi (Ziel: Zero 2 W, Pi OS Lite 64-Bit) für den
# Machbarkeitstest ein: Browser mit Widevine, PipeWire/Bluetooth, zram,
# Speicher-Tuning. Aufruf: sudo ./setup.sh [--no-tune-boot] [--browser=auto|chromium|chrome]
set -euo pipefail

TUNE_BOOT=1
BROWSER=auto
for arg in "$@"; do
  case $arg in
    --no-tune-boot) TUNE_BOOT=0 ;;
    --browser=*) BROWSER=${arg#*=} ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\n==> %s\n' "$*"; }
die() { echo "FEHLER: $*" >&2; exit 1; }
apt_has() { [[ -n $(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ && $2 != "(none)" {print $2}') ]]; }

[[ $EUID -eq 0 ]] || die "Bitte mit sudo starten."
TARGET_USER=${SUDO_USER:-}
[[ -n $TARGET_USER && $TARGET_USER != root ]] || die "Bitte als normaler Benutzer per sudo starten, nicht direkt als root."
TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
ARCH=$(dpkg --print-architecture)
[[ $ARCH == arm64 || $ARCH == amd64 ]] || die "64-Bit-System nötig (arm64), gefunden: $ARCH. Bitte Pi OS Lite 64-Bit installieren."

log "Paketlisten aktualisieren"
apt-get update

# Ist bereits zram aktiv (z. B. neueres Pi OS), kein zweites zram-Paket installieren.
PRE_ZRAM=0
swapon --noheadings --show=NAME 2>/dev/null | grep -q zram && PRE_ZRAM=1

log "Basis-Pakete installieren"
PKGS=(python3 python3-aiohttp pipewire pipewire-pulse wireplumber pulseaudio-utils bluez curl gpg)
(( PRE_ZRAM )) || PKGS+=(zram-tools)
apt_has libspa-0.2-bluetooth && PKGS+=(libspa-0.2-bluetooth)
apt-get install -y --no-install-recommends "${PKGS[@]}"

# --- Browser mit Widevine -----------------------------------------------------
install_chromium() {
  local pkg=""
  for p in chromium chromium-browser; do apt_has "$p" && { pkg=$p; break; }; done
  [[ -n $pkg ]] || return 1
  apt-get install -y --no-install-recommends "$pkg"
  if apt_has libwidevinecdm0; then
    apt-get install -y libwidevinecdm0
  else
    echo "WARNUNG: Paket libwidevinecdm0 nicht verfügbar – Chromium hat dann kein Widevine."
    return 1
  fi
}
install_chrome() {
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor --yes -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update
  if ! apt_has google-chrome-stable; then
    rm -f /etc/apt/sources.list.d/google-chrome.list
    apt-get update
    return 1
  fi
  apt-get install -y google-chrome-stable
}

log "Browser installieren (Modus: $BROWSER)"
case $BROWSER in
  chromium) install_chromium || die "Chromium mit Widevine nicht installierbar." ;;
  chrome)   install_chrome   || die "Google Chrome für $ARCH nicht im Google-Paketarchiv." ;;
  auto)
    # Auf Pi OS ist Chromium + libwidevinecdm0 der etablierte Weg, sonst offizielles Chrome.
    if [[ -f /etc/rpi-issue ]] && install_chromium; then :
    elif install_chrome; then :
    else install_chromium || die "Kein Browser mit Widevine installierbar."
    fi ;;
  *) die "Unbekannter Browser-Modus: $BROWSER" ;;
esac

# --- zram statt Swap auf der SD-Karte -----------------------------------------
log "zram (komprimierter Swap im RAM) einrichten"
if systemctl cat dphys-swapfile.service >/dev/null 2>&1; then
  systemctl disable --now dphys-swapfile || true
  echo "Swap-Datei auf der SD-Karte (dphys-swapfile) deaktiviert."
fi
if (( PRE_ZRAM )); then
  echo "zram ist bereits durch das System aktiv – unverändert gelassen."
else
  [[ -f /etc/default/zramswap && ! -f /etc/default/zramswap.zero-feasibility.bak ]] \
    && cp /etc/default/zramswap /etc/default/zramswap.zero-feasibility.bak
  printf 'ALGO=zstd\nPERCENT=75\nPRIORITY=100\n' > /etc/default/zramswap
  systemctl enable zramswap >/dev/null
  if ! systemctl restart zramswap; then
    echo "zstd nicht verfügbar – nutze lz4."
    printf 'ALGO=lz4\nPERCENT=75\nPRIORITY=100\n' > /etc/default/zramswap
    systemctl restart zramswap
  fi
fi
printf 'vm.swappiness=150\nvm.page-cluster=0\n' > /etc/sysctl.d/90-zero-feasibility.conf
sysctl --system >/dev/null

# --- PipeWire/Bluetooth ohne Desktop-Sitzung ----------------------------------
log "PipeWire und Bluetooth für den Betrieb ohne Bildschirm einrichten"
loginctl enable-linger "$TARGET_USER"
usermod -aG bluetooth,audio "$TARGET_USER" || true
WP_VER=$(wireplumber --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)
if [[ $WP_VER == 0.4 ]]; then
  dir="$TARGET_HOME/.config/wireplumber/bluetooth.lua.d"
  install -d -o "$TARGET_USER" -g "$TARGET_USER" "$dir"
  echo 'bluez_monitor.properties["with-logind"] = false' > "$dir/90-zero-feasibility.lua"
  chown "$TARGET_USER:" "$dir/90-zero-feasibility.lua"
else
  dir="$TARGET_HOME/.config/wireplumber/wireplumber.conf.d"
  install -d -o "$TARGET_USER" -g "$TARGET_USER" "$dir"
  printf 'wireplumber.profiles = {\n  main = {\n    monitor.bluez.seat-monitoring = disabled\n  }\n}\n' \
    > "$dir/90-zero-feasibility.conf"
  chown "$TARGET_USER:" "$dir/90-zero-feasibility.conf"
fi
systemctl enable --now bluetooth >/dev/null

# --- Grafikspeicher freigeben (nur ohne Bildschirm sinnvoll) -------------------
NEED_REBOOT=0
CFG=/boot/firmware/config.txt
[[ -f $CFG ]] || CFG=/boot/config.txt
if (( TUNE_BOOT )) && [[ -f $CFG ]]; then
  log "Grafikspeicher freigeben ($CFG, Sicherung: $CFG.zero-feasibility.bak)"
  [[ -f $CFG.zero-feasibility.bak ]] || cp "$CFG" "$CFG.zero-feasibility.bak"
  # Der KMS-Grafiktreiber reserviert Speicher (CMA), der ohne Bildschirm brachliegt.
  sed -i -E 's/^(dtoverlay=vc4-f?kms-v3d.*)$/#\1/' "$CFG"
  if grep -q '^gpu_mem=' "$CFG"; then
    sed -i -E 's/^gpu_mem=.*/gpu_mem=16/' "$CFG"
  else
    printf '\n[all]\ngpu_mem=16\n' >> "$CFG"
  fi
  NEED_REBOOT=1
  echo "Rückgängig: sudo cp $CFG.zero-feasibility.bak $CFG && sudo reboot"
fi

log "Fertig"
BIN=$(command -v google-chrome-stable || command -v chromium || command -v chromium-browser || true)
echo "Browser:      ${BIN:-nicht gefunden}"
echo "Arbeitsspeicher: $(awk '/MemTotal/ {print int($2/1024)" MB"}' /proc/meminfo)"
echo "Swap:         $(swapon --noheadings --show=NAME,SIZE | tr '\n' ' ')"
if (( NEED_REBOOT )); then
  echo
  echo "Bitte jetzt neu starten: sudo reboot"
fi
echo "Danach als $TARGET_USER (ohne sudo): siehe README.md, Schritt 2."
