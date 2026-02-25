#!/bin/sh
# Minimal display affinity helper:
# - optionally set CPU governor to performance
# - de-prioritize display.service so UI work is less likely to interfere
#   with Klipper/Moonraker on low-power SBCs

set -eu

TAG="display-affinity-minimal"
ENABLE_PERFORMANCE_GOVERNOR="${ENABLE_PERFORMANCE_GOVERNOR:-yes}"

log() {
  logger -t "$TAG" -- "$@" 2>/dev/null || true
  printf '%s: %s\n' "$TAG" "$*"
}

have() { command -v "$1" >/dev/null 2>&1; }

# Re-exec as root because systemd may call this via affinity.service.
if [ "$(id -u)" != 0 ]; then
  exec sudo -E -- "$0" "$@"
fi

mainpid() {
  unit="$1"
  systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0
}

renice_unit() {
  unit="$1"
  nice_val="$2"
  pid="$(mainpid "$unit")"
  [ "$pid" -gt 0 ] || return 0
  renice "$nice_val" -p "$pid" >/dev/null 2>&1 || true
}

ionice_idle_unit() {
  unit="$1"
  pid="$(mainpid "$unit")"
  [ "$pid" -gt 0 ] || return 0
  have ionice || return 0
  ionice -c3 -p "$pid" >/dev/null 2>&1 || true
}

set_performance_governor() {
  [ "$ENABLE_PERFORMANCE_GOVERNOR" = "yes" ] || {
    log "Skipping CPU governor change"
    return 0
  }

  if have cpupower; then
    cpupower frequency-set -g performance >/dev/null 2>&1 || true
  else
    for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
      [ -w "$g" ] && echo performance > "$g" 2>/dev/null || true
    done
  fi
  log "CPU governor set to performance (best effort)"
}

set_performance_governor

# Keep the UI process gentle. Do not touch klipper/klipper-mcu scheduling,
# CPU affinity, IRQ affinity, or serial driver tuning here.
renice_unit display.service 19
ionice_idle_unit display.service
log "Applied gentle priority tuning to display.service"

exit 0
