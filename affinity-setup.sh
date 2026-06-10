#!/bin/sh
# Minimal display affinity helper:
# - optionally set CPU governor to schedutil/ondemand
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

  # Use schedutil (preferred) or ondemand as fallback — not performance.
  # On fanless SBCs, performance mode keeps all cores at max frequency even
  # when idle, causing thermal throttling that hurts Klipper more than it helps.
  # schedutil/ondemand ramps quickly for Klipper bursts while staying cool at rest.
  applied_governor=""
  if have cpupower; then
    if cpupower frequency-set -g schedutil >/dev/null 2>&1; then
      applied_governor="schedutil"
    elif cpupower frequency-set -g ondemand >/dev/null 2>&1; then
      applied_governor="ondemand"
    fi
  else
    for gov_file in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
      if echo schedutil > "$gov_file" 2>/dev/null; then
        applied_governor="schedutil"
      elif echo ondemand > "$gov_file" 2>/dev/null; then
        applied_governor="ondemand"
      fi
    done
  fi
  if [ -n "$applied_governor" ]; then
    log "CPU governor applied: $applied_governor where supported (best effort)"
  else
    log "CPU governor unchanged; schedutil/ondemand not available or not writable"
  fi
}

set_performance_governor

# Keep the UI process gentle. Do not touch klipper/klipper-mcu scheduling,
# CPU affinity, IRQ affinity, or serial driver tuning here.
renice_unit display.service 19
ionice_idle_unit display.service
log "Applied gentle priority tuning to display.service"

exit 0
