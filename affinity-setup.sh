#!/bin/sh
# Klipper stack affinity + PREEMPT_RT realtime setup (no unit file edits on disk)
# Auto-detects multiprocessing plugins (Cartographer, Beacon, IDM) and handles
# child process migration + continuous thread pinning.

set -eu

TAG="affinity-setup"
log() {
  logger -t "$TAG" -- "$@"
  printf '%s: %s\n' "$TAG" "$*"
}

# Re-exec as root if needed
if [ "$(id -u)" != 0 ]; then
  exec sudo -E -- "$0" "$@"
fi

# --- CPU layout (0-based) ----------------------------------------------------
MISC_CPU=0               # moonraker/mobileraker/mjpg-streamer/power_monitor + ttyS2 IRQ
DISPLAY_TTY_CPU=1        # display.service + ttyS1 IRQ
KLIPPER_MCU_RPI_CPU=2    # klipper-mcu.service (host-MCU tasks)
KLIPPER_MCU_TTY_CPU=3    # klipper.service + ttyS0 IRQ

KLIPPER_CPUS_WIDE="0,3"  # widened cgroup for child migration

# --- auto-detection of multiprocessing plugins -------------------------------
# Scans klippy logs for evidence of loaded plugins that use multiprocessing.
# More reliable than config parsing: catches includes, conditional configs,
# and confirms the plugin actually loaded successfully.
detect_multiprocessing_plugins() {
  log_paths="
    /home/*/printer_data/logs/klippy.log*
    /home/*/klipper_logs/klippy.log*
  "
  
  # Patterns indicating multiprocessing plugins loaded:
  #   [cartographer] - Cartographer probe (eddy current)
  #   [scanner]      - Cartographer v5+ / Survey Touch
  #   [beacon]       - Beacon probe (eddy current)
  #   [mcu eddy]     - BTT Eddy MCU definition (space distinguishes from other mcus)
  #   btt_eddy       - BTT Eddy references in config/loading
  #   [idm]          - IDM probe
  pattern='\[cartographer\]|\[scanner\]|\[beacon\]|\[mcu eddy\]|btt_eddy|\[idm\]'
  
  # shellcheck disable=SC2086
  for glob in $log_paths; do
    for f in $glob; do
      [ -f "$f" ] || continue
      # Search first 5000 lines (startup/config loading section) to avoid
      # scanning entire multi-MB logs; plugins appear early during init
      if head -n 5000 "$f" 2>/dev/null | grep -qE "$pattern"; then
        log "Detected multiprocessing plugin in $f"
        return 0
      fi
    done
  done
  
  return 1
}

# --- basic env checks (warn-only) --------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }
if systemctl is-active --quiet irqbalance.service 2>/dev/null; then
  log "WARN: irqbalance is active; it may override IRQ affinities."
fi
for bin in systemctl awk ps sed chrt taskset ionice renice stty sysctl logger grep; do
  have "$bin" || log "WARN: missing helper '$bin' (some steps may be skipped)."
done

cpu_online() {
  c="$1"
  [ -d "/sys/devices/system/cpu/cpu$c" ] || return 1
  onf="/sys/devices/system/cpu/cpu$c/online"
  [ ! -f "$onf" ] || [ "$(cat "$onf" 2>/dev/null || echo 1)" = "1" ]
}

# --- helpers -----------------------------------------------------------------
wait_active() {
  unit="$1"; t=0
  while [ "$t" -lt 30 ]; do
    state=$(systemctl is-active "$unit" 2>/dev/null || true)
    pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    if [ "$state" = "active" ] && [ "${pid:-0}" -gt 0 ]; then
      return 0
    fi
    sleep 0.5
    t=$((t+1))
  done
  log "WARN: $unit did not become active in time; continuing."
  return 0
}

wait_irq_present() {
  dev="$1"; t=0
  while [ "$t" -lt 20 ]; do
    irq=$(awk -v n="$dev" '$NF==n{gsub(":", "", $1); print $1; exit}' /proc/interrupts)
    [ -n "$irq" ] && return 0
    sleep 0.5
    t=$((t+1))
  done
  log "WARN: IRQ for $dev not found; continuing."
  return 0
}

irq_for() {
  awk -v name="$1" '$NF==name{gsub(":", "", $1); print $1; exit}' /proc/interrupts
}

pin_irq() {
  irq="$1"; cpu="$2"
  [ -n "$irq" ] || return 0
  p="/proc/irq/$irq"
  [ -d "$p" ] || return 0
  cpu_online "$cpu" || { log "WARN: CPU $cpu not online; skip pin IRQ $irq"; return 0; }

  if [ -w "$p/smp_affinity_list" ]; then
    echo "$cpu" > "$p/smp_affinity_list" 2>/dev/null || true
  else
    printf '%x\n' "$((1<<cpu))" > "$p/smp_affinity" 2>/dev/null || true
  fi
  log "Pinned IRQ $irq to CPU $cpu"
}

set_unit_cpus() {
  unit="$1"; cpus="$2"
  case "$cpus" in
    *,*|*-*) ;;
    *) cpu_online "$cpus" || { log "WARN: CPU $cpus not online; skip $unit CPU pin"; return 0; } ;;
  esac
  if systemctl set-property --runtime "$unit" "AllowedCPUs=$cpus" >/dev/null 2>&1; then
    log "AllowedCPUs for $unit -> $cpus"
    return 0
  else
    pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
    if [ "${pid:-0}" -gt 0 ] && taskset -pc "$cpus" "$pid" >/dev/null 2>&1; then
      log "taskset fallback for $unit(pid=$pid) -> $cpus"
      return 0
    fi
  fi
  return 1
}

renice_unit() {
  unit="$1"; niceval="$2"
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  if [ "${pid:-0}" -gt 0 ] && renice -n "$niceval" -p "$pid" >/dev/null 2>&1; then
    log "renice $unit(pid=$pid) -> $niceval"
  fi
  return 0
}

ionice_idle_unit() {
  unit="$1"
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  if [ "${pid:-0}" -gt 0 ] && ionice -c3 -p "$pid" >/dev/null 2>&1; then
    log "ionice idle $unit(pid=$pid)"
  fi
  return 0
}

ps_line() {
  pid="$1"
  ps -o pid,cls,rtprio,psr,cmd -p "$pid" --no-headers 2>/dev/null | sed 's/^/    /'
}

promote_unit_fifo() {
  unit="$1"; prio="$2"
  systemctl set-property --runtime "$unit" CPUSchedulingPolicy=fifo CPUSchedulingPriority="$prio" >/dev/null 2>&1 || true
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  [ "${pid:-0}" -gt 0 ] || return 0
  n=0
  while [ "$n" -lt 10 ]; do
    chrt -a -f -p "$prio" "$pid" >/dev/null 2>&1 || true
    cls=$(ps -o cls= -p "$pid" 2>/dev/null | xargs || true)
    rt=$(ps -o rtprio= -p "$pid" 2>/dev/null | xargs || true)
    if [ "$cls" = "FF" ] && [ "$rt" = "$prio" ]; then
      log "$unit(pid=$pid) -> FIFO $prio (all threads)"
      return 0
    fi
    sleep 0.3
    n=$((n+1))
  done
  log "WARN: $unit(pid=$pid) did not reach FIFO $prio (last: cls=$cls rtprio=$rt)"
  return 0
}

chrt_irq_thread() {
  irq="$1"; prio="$2"; t=0
  [ -n "$irq" ] || return 0
  while [ "$t" -lt 20 ]; do
    pid=$(
      ps -eLo pid=,cmd= 2>/dev/null | awk -v irq="$irq" '
        {
          pid=$1; $1=""; sub(/^[ \t]+/,""); name=$0;
          gsub(/^\[/,"",name); gsub(/\]$/,"",name);
          if (name ~ ("^irq/" irq "-")) { print pid; exit }
        }'
    )
    if [ -n "$pid" ]; then
      chrt -f -p "$prio" "$pid" >/dev/null 2>&1 || true
      log "IRQ thread irq/$irq -> FIFO $prio (pid=$pid)"
      return 0
    fi
    sleep 0.5
    t=$((t+1))
  done
  log "WARN: did not find threaded IRQ for $irq"
  return 0
}

# --- multiprocessing support -------------------------------------------------
# Widens klipper cgroup AFTER RT promotion, immediately pins all threads,
# then starts monitor for ongoing thread/child management.

widen_and_monitor_klipper() {
  main_pid=$(systemctl show -p MainPID --value klipper.service 2>/dev/null || echo 0)
  [ "${main_pid:-0}" -gt 0 ] || return 0
  
  children_file="/proc/$main_pid/task/$main_pid/children"
  [ -f "$children_file" ] || {
    log "WARN: /proc children file unavailable (CONFIG_PROC_CHILDREN=n?); child monitor disabled"
    # Continue anyway - thread monitoring still useful
  }
  
  # Widen cgroup to allow children on CPU 0
  if ! systemctl set-property --runtime klipper.service "AllowedCPUs=$KLIPPER_CPUS_WIDE" >/dev/null 2>&1; then
    log "WARN: could not widen klipper cgroup; multiprocessing children will run on CPU $KLIPPER_MCU_TTY_CPU"
    return 0
  fi
  
  # Immediately pin all existing threads to CPU 3 (no race window)
  taskset -apc "$KLIPPER_MCU_TTY_CPU" "$main_pid" >/dev/null 2>&1 || true
  log "Widened klipper cgroup to $KLIPPER_CPUS_WIDE, pinned existing threads to CPU $KLIPPER_MCU_TTY_CPU"
  
  # Start combined thread + child monitor
  log "Starting klipper thread/child monitor for pid $main_pid"
  
  (
    seen_children=""
    target_mask=$(printf '%x' $((1 << KLIPPER_MCU_TTY_CPU)))
    
    while kill -0 "$main_pid" 2>/dev/null; do
      # --- Pin any new/migrated threads in main process to CPU 3 ---
      for tid_path in /proc/"$main_pid"/task/*; do
        tid="${tid_path##*/}"
        [ -d "$tid_path" ] || continue
        
        # Check current affinity - only touch if not already correct
        current=$(cat "$tid_path/status" 2>/dev/null | awk '/^Cpus_allowed:/{print $2}' || echo "")
        if [ -n "$current" ] && [ "$current" != "$target_mask" ]; then
          taskset -pc "$KLIPPER_MCU_TTY_CPU" "$tid" >/dev/null 2>&1 || true
        fi
      done
      
      # --- Migrate child processes to CPU 0 ---
      if [ -f "$children_file" ]; then
        for cpid in $(cat "$children_file" 2>/dev/null); do
          case " $seen_children " in
            *" $cpid "*) continue ;;
          esac
          
          if [ -d "/proc/$cpid" ]; then
            tgid=$(awk '/^Tgid:/{print $2}' "/proc/$cpid/status" 2>/dev/null || echo "")
            if [ "$tgid" = "$cpid" ]; then
              taskset -apc "$MISC_CPU" "$cpid" >/dev/null 2>&1 && \
                logger -t "$TAG" "klipper child $cpid -> CPU $MISC_CPU"
              renice -n 15 -p "$cpid" >/dev/null 2>&1 || true
              ionice -c3 -p "$cpid" >/dev/null 2>&1 || true
              seen_children="$seen_children $cpid"
            fi
          fi
        done
      fi
      
      # 250ms poll: balance between responsiveness and overhead
      sleep 0.25
    done
    
    logger -t "$TAG" "klipper monitor exiting (main process gone)"
  ) &
  
  monitor_pid=$!
  taskset -pc "$MISC_CPU" "$monitor_pid" >/dev/null 2>&1 || true
  renice -n 19 -p "$monitor_pid" >/dev/null 2>&1 || true
  ionice -c3 -p "$monitor_pid" >/dev/null 2>&1 || true
  
  log "Thread/child monitor running as pid $monitor_pid on CPU $MISC_CPU"
}

# --- wait for services -------------------------------------------------------
for u in klipper.service klipper-mcu.service moonraker.service display.service; do
  wait_active "$u"
done

# --- auto-detect multiprocessing plugins -------------------------------------
MULTIPROCESSING_DETECTED=0
if detect_multiprocessing_plugins; then
  MULTIPROCESSING_DETECTED=1
  log "Multiprocessing plugin support enabled"
else
  log "No multiprocessing plugins detected; using standard pinning"
fi

# --- wait for UART IRQs ------------------------------------------------------
wait_irq_present ttyS0
wait_irq_present ttyS1
wait_irq_present ttyS2

# --- pin UART IRQs -----------------------------------------------------------
IRQ_S0="$(irq_for ttyS0 || true)"
IRQ_S1="$(irq_for ttyS1 || true)"
IRQ_S2="$(irq_for ttyS2 || true)"

[ -n "${IRQ_S0:-}" ] && pin_irq "$IRQ_S0" "$KLIPPER_MCU_TTY_CPU"
[ -n "${IRQ_S1:-}" ] && pin_irq "$IRQ_S1" "$DISPLAY_TTY_CPU"
[ -n "${IRQ_S2:-}" ] && pin_irq "$IRQ_S2" "$MISC_CPU"

# --- place units on CPUs (klipper gets single CPU initially) -----------------
set_unit_cpus klipper-mcu.service "$KLIPPER_MCU_RPI_CPU"
set_unit_cpus klipper.service     "$KLIPPER_MCU_TTY_CPU"
set_unit_cpus display.service     "$DISPLAY_TTY_CPU"
set_unit_cpus moonraker.service   "$MISC_CPU"
set_unit_cpus mjpg-streamer-webcam1.service "$MISC_CPU" || true
set_unit_cpus mobileraker.service            "$MISC_CPU" || true
set_unit_cpus power_monitor.service          "$MISC_CPU" || true

# --- serial tuning for /dev/ttyS0 -------------------------------------------
if [ -e /dev/ttyS0 ]; then
  have setserial && setserial /dev/ttyS0 low_latency || true
  stty -F /dev/ttyS0 cs8 -parenb -cstopb -ixon -ixoff -crtscts \
       -icanon -echo -echoe -echok -echoctl -echoke -iexten \
       -inlcr -igncr -icrnl -opost -hupcl min 1 time 0 || true
else
  log "WARN: /dev/ttyS0 not present; skipped stty/setserial"
fi

# --- make display gentle -----------------------------------------------------
renice_unit      display.service 19
ionice_idle_unit display.service

# --- RT budget ---------------------------------------------------------------
sysctl -w kernel.sched_rt_runtime_us=-1 >/dev/null 2>&1 || \
  echo -1 > /proc/sys/kernel/sched_rt_runtime_us 2>/dev/null || \
  log "WARN: failed to set sched_rt_runtime_us"

# --- promote Klippy + host MCU to SCHED_FIFO 60 (sticky) ---------------------
promote_unit_fifo klipper-mcu.service 60
promote_unit_fifo klipper.service     60

# --- multiprocessing support (only if plugin detected) -----------------------
# Done AFTER RT promotion to avoid race window
if [ "$MULTIPROCESSING_DETECTED" = "1" ]; then
  widen_and_monitor_klipper
fi

# --- bump ttyS0 IRQ thread if present ----------------------------------------
if [ -n "${IRQ_S0:-}" ]; then
  chrt_irq_thread "$IRQ_S0" 70
fi

# --- summary -----------------------------------------------------------------
if [ -n "${IRQ_S0:-}" ]; then
  aff0=$(cat "/proc/irq/$IRQ_S0/smp_affinity_list" 2>/dev/null || echo "?")
  log "ttyS0 irq=$IRQ_S0 aff=$aff0"
fi
if [ -n "${IRQ_S1:-}" ]; then
  aff1=$(cat "/proc/irq/$IRQ_S1/smp_affinity_list" 2>/dev/null || echo "?")
  log "ttyS1 irq=$IRQ_S1 aff=$aff1"
fi
if [ -n "${IRQ_S2:-}" ]; then
  aff2=$(cat "/proc/irq/$IRQ_S2/smp_affinity_list" 2>/dev/null || echo "?")
  log "ttyS2 irq=$IRQ_S2 aff=$aff2"
fi

log "klipper-mcu:$(ps_line "$(systemctl show -p MainPID --value klipper-mcu.service 2>/dev/null || echo 0)" || true)"
log "klipper:    $(ps_line "$(systemctl show -p MainPID --value klipper.service 2>/dev/null || echo 0)" || true)"
log "done (IRQs: ttyS0:${IRQ_S0:-?} ttyS1:${IRQ_S1:-?} ttyS2:${IRQ_S2:-?}, multiprocessing=$MULTIPROCESSING_DETECTED)"
exit 0
