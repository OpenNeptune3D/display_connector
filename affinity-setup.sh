#!/bin/sh
# Robust, idempotent affinity & RT setup for Klipper stack
# - Pins UART IRQs dynamically by name (ttyS0/ttyS1/ttyS2)
# - Sets cpuset (AllowedCPUs=) with fallback to taskset
# - Applies priorities without editing vendor unit files
# - Waits for services and IRQs to exist to avoid boot races
# - Keeps Klippy non-RT (nice -5); only klipper-mcu is RT

set -eu

# CPU layout (0-based):
MISC_CPU=0             # ttyS2 IRQ (linux console serial) + Moonraker + Mobileraker + mjpg-streamer + power_monitor
DISPLAY_TTY_CPU=1      # ttyS1 IRQ (display serial) + display.service
KLIPPER_MCU_RPI_CPU=2  # klipper-mcu.service (Linux host MCU: ADXL/LED)
KLIPPER_MCU_TTY_CPU=3  # ttyS0 IRQ (klipper serial) + klipper.service

# --- wait helpers ----------------------------------------------------------
wait_active() { # wait until unit is active and has a PID (max ~15s)
  unit="$1"; t=0
  while [ $t -lt 30 ]; do
    state=$(systemctl is-active "$unit" 2>/dev/null || true)
    pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    if [ "$state" = "active" ] && [ "${pid:-0}" -gt 0 ]; then
      return 0
    fi
    sleep 0.5; t=$((t+1))
  done
  return 0
}

wait_irq_present() { # wait until /proc/interrupts shows the device (max ~10s)
  dev="$1"; t=0
  while [ $t -lt 20 ]; do
    irq=$(awk -v n="$dev" '$NF==n{gsub(":", "", $1); print $1; exit}' /proc/interrupts)
    [ -n "$irq" ] && return 0
    sleep 0.5; t=$((t+1))
  done
  return 0
}

# --- helpers ---------------------------------------------------------------
irq_for() { awk -v name="$1" '$NF==name{gsub(":", "", $1); print $1; exit}' /proc/interrupts; }

pin_irq() {
  irq="$1"; cpu="$2"
  [ -n "$irq" ] || return 0
  path="/proc/irq/$irq"
  [ -d "$path" ] || return 0
  if [ -w "$path/smp_affinity_list" ]; then
    echo "$cpu" > "$path/smp_affinity_list" || true
  else
    printf '%x\n' $((1<<cpu)) > "$path/smp_affinity" || true
  fi
}

# Set CPUs for a unit: prefer cpuset (AllowedCPUs), else taskset the PID
set_unit_cpus() {
  unit="$1"; cpus="$2"
  if systemctl set-property --runtime "$unit" "AllowedCPUs=$cpus" >/dev/null 2>&1; then
    return 0
  fi
  pid="$(systemctl show -p MainPID --value "$unit" 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 0 ] && taskset -pc "$cpus" "$pid" >/dev/null 2>&1 || true
}

renice_unit() {
  unit="$1"; niceval="$2"
  pid="$(systemctl show -p MainPID --value "$unit" 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 0 ] && renice -n "$niceval" -p "$pid" >/dev/null 2>&1 || true
}

ionice_unit_idle() {
  unit="$1"
  pid="$(systemctl show -p MainPID --value "$unit" 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 0 ] && ionice -c3 -p "$pid" >/dev/null 2>&1 || true
}

chrt_fifo_unit() {
  unit="$1"; prio="$2"
  pid="$(systemctl show -p MainPID --value "$unit" 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 0 ] && chrt -f -p "$prio" "$pid" >/dev/null 2>&1 || true
}

# Make an IRQ kernel thread (irq/<N>-*) SCHED_FIFO (only if threaded IRQs exist)
chrt_irq_thread() {
  irq="$1"; prio="$2"; t=0
  [ -n "$irq" ] || return 0
  while [ $t -lt 20 ]; do
    pid=$(ps -eo pid=,cmd= 2>/dev/null | awk -v irq="$irq" '$0 ~ ("^irq/" irq "-"){print $1; exit}')
    if [ -n "$pid" ]; then
      chrt -f -p "$prio" "$pid" >/dev/null 2>&1 || true
      return 0
    fi
    sleep 0.5; t=$((t+1))
  done
  return 0
}

# --- prep (avoid RT starvation; allow but bound RT CPU) -------------------
# Use default throttling (950ms of RT per 1s period) to keep softirqs healthy.
sysctl -w kernel.sched_rt_runtime_us=950000 >/dev/null 2>&1 || true

# Ensure services and IRQs exist (handle boot races)
wait_active klipper.service
wait_active klipper-mcu.service
wait_active moonraker.service
wait_active display.service
wait_irq_present ttyS0
wait_irq_present ttyS1
wait_irq_present ttyS2

# --- IRQ pinning (by name, dynamic) ---------------------------------------
IRQ_S0="$(irq_for ttyS0 || true)"
IRQ_S1="$(irq_for ttyS1 || true)"
IRQ_S2="$(irq_for ttyS2 || true)"
[ -n "${IRQ_S0:-}" ] && pin_irq "$IRQ_S0" "$KLIPPER_MCU_TTY_CPU"   # klippy consumer lives here
[ -n "${IRQ_S1:-}" ] && pin_irq "$IRQ_S1" "$DISPLAY_TTY_CPU"
[ -n "${IRQ_S2:-}" ] && pin_irq "$IRQ_S2" "$MISC_CPU"

# --- Serial tuning for MCU UART (leave speed to Klippy) -------------------
command -v setserial >/dev/null 2>&1 && setserial /dev/ttyS0 low_latency || true
# If RTS/CTS is actually wired end-to-end, change '-crtscts' to 'crtscts'
stty -F /dev/ttyS0 cs8 -parenb -cstopb -ixon -ixoff -crtscts -icanon -echo -echoe -echok -echoctl -echoke -iexten -inlcr -igncr -icrnl -opost -hupcl min 1 time 0 || true

# --- Unit cpus & priorities ------------------------------------------------
set_unit_cpus klipper-mcu.service "$KLIPPER_MCU_RPI_CPU"
set_unit_cpus klipper.service     "$KLIPPER_MCU_TTY_CPU"
set_unit_cpus display.service     "$DISPLAY_TTY_CPU"
set_unit_cpus moonraker.service   "$MISC_CPU"
set_unit_cpus mjpg-streamer-webcam1.service "$MISC_CPU"
set_unit_cpus mobileraker.service "$MISC_CPU"
set_unit_cpus power_monitor.service "$MISC_CPU"

# Make display gentle (no bursty quotas; tiny CPU weight; low prio + idle IO)
systemctl set-property --runtime display.service CPUQuota= >/dev/null 2>&1 || true
systemctl set-property --runtime display.service CPUWeight=1 >/dev/null 2>&1 || true
renice_unit       display.service 19
ionice_unit_idle  display.service

# Realtime/priority tuning
# Host MCU process should be RT to service GPIO/ADXL timing
chrt_fifo_unit    klipper-mcu.service 60

# Klippy stays non-RT; slight scheduling preference
renice_unit       klipper.service -5

# If UART IRQs are threaded (PREEMPT_RT or 'threadirqs'), prefer the ttyS0 IRQ thread slightly above host-MCU
if [ -n "${IRQ_S0:-}" ] && ps -eLo cmd | awk -v i="$IRQ_S0" '$0 ~ ("^irq/" i "-"){found=1} END{exit found?0:1}'; then
  chrt_irq_thread "$IRQ_S0" 70
fi

exit 0
