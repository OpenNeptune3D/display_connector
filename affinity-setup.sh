#!/bin/sh
# Klipper stack affinity + low-jitter tuning (MCU-safe, PREEMPT_RT aware)
# Implements: CPU governor lock, irqbalance neutralization, polling IRQ discovery
# Avoids: FIFO promotion, RT throttle disable, kernel isolation

set -eu

TAG="klipper-affinity-safe"
log() {
  logger -t "$TAG" -- "$@"
  printf '%s: %s\n' "$TAG" "$*"
}

# ---------------- Re-exec as root ----------------
if [ "$(id -u)" != 0 ]; then
  exec sudo -E -- "$0" "$@"
fi

# ---------------- CPU layout (0-based) ----------------
MISC_CPU=0               # moonraker, webcam, power monitor, ttyS2
DISPLAY_CPU=1            # display.service, ttyS1
KLIPPER_CPU=2            # klipper.service + ttyS0 IRQ
KLIPPER_MCU_CPU=3        # klipper-mcu.service

# ---- Optional: co-locate klipper-mcu with klipper (cache locality vs contention)
# KLIPPER_MCU_CPU=$KLIPPER_CPU

# ---- Optional: demote FIFO processes to CFS before renicing
# Set to "yes" to force CFS scheduling (safer), "no" to leave existing scheduler
DEMOTE_FIFO_TO_CFS="no"

# ---------------- Helpers ----------------
have() { command -v "$1" >/dev/null 2>&1; }

for bin in systemctl awk ps sed taskset ionice renice stty chrt cpupower logger; do
  have "$bin" || log "WARN: missing helper '$bin'"
done

cpu_online() {
  c="$1"
  [ -d "/sys/devices/system/cpu/cpu$c" ] || return 1
  onf="/sys/devices/system/cpu/cpu$c/online"
  [ ! -f "$onf" ] || [ "$(cat "$onf")" = "1" ]
}

wait_active() {
  unit="$1"; t=0
  while [ "$t" -lt 30 ]; do
    pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    [ "$pid" -gt 0 ] && return 0
    sleep 0.5
    t=$((t+1))
  done
  log "WARN: $unit did not become active"
}

irq_for() {
  awk -v name="$1" '$NF==name{gsub(":", "", $1); print $1; exit}' /proc/interrupts
}

# Poll for IRQ to appear (handles lazy IRQ registration)
poll_irq() {
  dev="$1"; timeout="${2:-10}"; t=0
  irq=""
  while [ "$t" -lt "$timeout" ]; do
    irq="$(irq_for "$dev" || true)"
    [ -n "$irq" ] && break
    sleep 1
    t=$((t+1))
  done
  echo "$irq"
}

pin_irq() {
  irq="$1"; cpu="$2"
  [ -n "$irq" ] || return 0
  cpu_online "$cpu" || return 0
  echo "$cpu" > "/proc/irq/$irq/smp_affinity_list" 2>/dev/null || true
  log "Pinned IRQ $irq -> CPU $cpu"
}

set_unit_cpus() {
  unit="$1"; cpu="$2"
  cpu_online "$cpu" || return 0
  if ! systemctl set-property --runtime "$unit" AllowedCPUs="$cpu" >/dev/null 2>&1; then
    pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    [ "$pid" -gt 0 ] && taskset -pc "$cpu" "$pid" >/dev/null 2>&1 || true
  fi
  log "Pinned $unit -> CPU $cpu"
}

# Demote RT (FIFO/RR) to CFS if enabled
demote_to_cfs() {
  unit="$1"
  [ "$DEMOTE_FIFO_TO_CFS" = "yes" ] || return 0
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  [ "$pid" -gt 0 ] || return 0
  # Check current scheduling class
  cls=$(ps -o cls= -p "$pid" 2>/dev/null || echo "TS")
  case "$cls" in
    FF|RR)
      chrt -o 0 -p "$pid" 2>/dev/null && log "Demoted $unit from $cls to CFS" || true
      ;;
  esac
}

renice_unit() {
  unit="$1"; nice="$2"
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  [ "$pid" -gt 0 ] && renice "$nice" -p "$pid" >/dev/null 2>&1 || true
}

ionice_idle_unit() {
  unit="$1"
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  [ "$pid" -gt 0 ] && ionice -c3 -p "$pid" >/dev/null 2>&1 || true
}

ps_line() {
  pid="$1"
  ps -o pid,cls,rtprio,ni,psr,cmd -p "$pid" --no-headers 2>/dev/null | sed 's/^/    /'
}

# ---------------- CPU governor: performance ----------------
if have cpupower; then
  cpupower frequency-set -g performance >/dev/null 2>&1 || true
else
  for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [ -w "$g" ] && echo performance > "$g" 2>/dev/null || true
  done
fi
log "CPU governor set to performance"

# ---------------- irqbalance neutralization ----------------
if systemctl is-active --quiet irqbalance.service 2>/dev/null; then
  systemctl stop irqbalance.service
  systemctl mask irqbalance.service
  log "irqbalance stopped and masked (run 'systemctl unmask irqbalance' to restore)"
fi

# ---------------- Wait for services ----------------
for u in klipper.service klipper-mcu.service moonraker.service display.service; do
  wait_active "$u"
done

# ---------------- IRQ discovery (polling) ----------------
log "Polling for UART IRQs..."
IRQ_S0="$(poll_irq ttyS0 10)"
IRQ_S1="$(poll_irq ttyS1 5)"
IRQ_S2="$(poll_irq ttyS2 5)"

[ -n "$IRQ_S0" ] || log "WARN: ttyS0 IRQ not found after polling"
[ -n "$IRQ_S1" ] || log "WARN: ttyS1 IRQ not found after polling"
[ -n "$IRQ_S2" ] || log "WARN: ttyS2 IRQ not found after polling"

# ---------------- IRQ affinity ----------------
[ -n "$IRQ_S0" ] && pin_irq "$IRQ_S0" "$KLIPPER_CPU"
[ -n "$IRQ_S1" ] && pin_irq "$IRQ_S1" "$DISPLAY_CPU"
[ -n "$IRQ_S2" ] && pin_irq "$IRQ_S2" "$MISC_CPU"

# ---------------- CPU affinity for services ----------------
set_unit_cpus klipper.service               "$KLIPPER_CPU"
set_unit_cpus klipper-mcu.service           "$KLIPPER_MCU_CPU"
set_unit_cpus display.service               "$DISPLAY_CPU"
set_unit_cpus moonraker.service             "$MISC_CPU"
set_unit_cpus mjpg-streamer-webcam1.service "$MISC_CPU" 2>/dev/null || true
set_unit_cpus mobileraker.service           "$MISC_CPU" 2>/dev/null || true
set_unit_cpus power_monitor.service         "$MISC_CPU" 2>/dev/null || true

# ---------------- Scheduler demotion (optional) ----------------
demote_to_cfs klipper.service
demote_to_cfs klipper-mcu.service

# ---------------- Priority tuning (CFS nice values) ----------------
renice_unit klipper.service     -18
renice_unit klipper-mcu.service -10

# ---------------- Make display/UI gentle ----------------
renice_unit      display.service 19
ionice_idle_unit display.service

# ---------------- Serial low-latency tuning ----------------
if [ -c /dev/ttyS0 ]; then
  have setserial && setserial /dev/ttyS0 low_latency 2>/dev/null || true
  stty -F /dev/ttyS0 raw -echo -ixon -ixoff min 1 time 0 2>/dev/null || true
else
  log "WARN: /dev/ttyS0 not a character device"
fi

# ---------------- Summary ----------------
log "ttyS0 irq=${IRQ_S0:-?}"
log "ttyS1 irq=${IRQ_S1:-?}"
log "ttyS2 irq=${IRQ_S2:-?}"

log "klipper:     $(ps_line "$(systemctl show -p MainPID --value klipper.service 2>/dev/null || echo 0)")"
log "klipper-mcu: $(ps_line "$(systemctl show -p MainPID --value klipper-mcu.service 2>/dev/null || echo 0)")"

if [ "$DEMOTE_FIFO_TO_CFS" = "yes" ]; then
  log "done (CFS mode forced, governor locked, irqbalance disabled)"
else
  log "done (scheduler unchanged, governor locked, irqbalance disabled)"
fi

exit 0
