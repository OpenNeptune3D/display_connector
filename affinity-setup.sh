#!/bin/sh
# Klipper stack affinity + PREEMPT_RT realtime setup (no unit file edits on disk)
# Auto-detects multiprocessing plugins (Cartographer, Beacon, IDM) and handles
# child process migration + continuous thread pinning.
#
# Fixes applied:
# - Child processes are demoted from inherited SCHED_FIFO to SCHED_OTHER
# - Cpus_allowed comparison handles leading zeros correctly
# - Faster 100ms polling for quicker child detection
# - Reduced thread re-pinning overhead (only on affinity drift)
# - Proper error handling throughout

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

# Monitor polling interval in seconds (100ms for responsive child detection)
MONITOR_POLL_INTERVAL="0.1"

# --- auto-detection of multiprocessing plugins -------------------------------
detect_multiprocessing_plugins() {
  log_paths="
    /home/*/printer_data/logs/klippy.log*
    /home/*/klipper_logs/klippy.log*
  "

  # Patterns indicating multiprocessing plugins loaded
  pattern='\[cartographer\]|\[scanner\]|\[beacon\]|\[mcu eddy\]|btt_eddy|\[idm\]'

  # shellcheck disable=SC2086
  for glob in $log_paths; do
    for f in $glob; do
      [ -f "$f" ] || continue
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

for bin in systemctl awk ps sed chrt taskset ionice renice stty sysctl logger grep pgrep; do
  have "$bin" || log "WARN: missing helper '$bin' (some steps may be skipped)."
done

cpu_online() {
  c="$1"
  [ -d "/sys/devices/system/cpu/cpu$c" ] || return 1
  onf="/sys/devices/system/cpu/cpu$c/online"
  [ ! -f "$onf" ] || [ "$(cat "$onf" 2>/dev/null || echo 1)" = "1" ]
}

# Validate CPU list (handles single CPU, ranges, and lists)
validate_cpu_list() {
  cpus="$1"
  case "$cpus" in
    *,*)
      # Comma-separated list: validate each part
      for part in $(echo "$cpus" | tr ',' ' '); do
        case "$part" in
          *-*) ;; # Range - assume valid
          *) cpu_online "$part" || return 1 ;;
        esac
      done
      ;;
    *-*) ;; # Range - assume valid
    *) cpu_online "$cpus" || return 1 ;;
  esac
  return 0
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

  validate_cpu_list "$cpus" || { log "WARN: CPU(s) $cpus not valid; skip $unit CPU pin"; return 0; }

  if systemctl set-property --runtime "$unit" "AllowedCPUs=$cpus" >/dev/null 2>&1; then
    log "AllowedCPUs for $unit -> $cpus"
    return 0
  fi

  # Fallback to taskset
  pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || echo 0)
  if [ "${pid:-0}" -gt 0 ] && taskset -pc "$cpus" "$pid" >/dev/null 2>&1; then
    log "taskset fallback for $unit(pid=$pid) -> $cpus"
    return 0
  fi

  log "WARN: could not set CPUs for $unit"
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
  [ "${pid:-0}" -gt 0 ] || return 0
  ps -o pid,cls,rtprio,psr,cmd -p "$pid" --no-headers 2>/dev/null | sed 's/^/    /' || true
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
MONITOR_PID_FILE="/run/klipper-affinity-monitor.pid"

kill_existing_monitor() {
  if [ -f "$MONITOR_PID_FILE" ]; then
    old_pid=$(cat "$MONITOR_PID_FILE" 2>/dev/null || echo "")
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      log "Stopping existing monitor (pid=$old_pid)"
      kill "$old_pid" 2>/dev/null || true
      sleep 0.2
    fi
    rm -f "$MONITOR_PID_FILE" 2>/dev/null || true
  fi
}

widen_and_monitor_klipper() {
  main_pid=$(systemctl show -p MainPID --value klipper.service 2>/dev/null || echo 0)
  [ "${main_pid:-0}" -gt 0 ] || return 0

  # Kill any existing monitor before starting a new one
  kill_existing_monitor

  children_file="/proc/$main_pid/task/$main_pid/children"
  has_children_file=0
  [ -f "$children_file" ] && has_children_file=1

  if [ "$has_children_file" = "0" ]; then
    log "WARN: /proc children file unavailable (CONFIG_PROC_CHILDREN=n?); using fallback child detection"
  fi

  # Widen cgroup to allow children on CPU 0
  if ! systemctl set-property --runtime klipper.service "AllowedCPUs=$KLIPPER_CPUS_WIDE" >/dev/null 2>&1; then
    log "WARN: could not widen klipper cgroup; multiprocessing children will run on CPU $KLIPPER_MCU_TTY_CPU"
    return 0
  fi

  # Immediately pin all existing threads to CPU 3 (no race window)
  taskset -apc "$KLIPPER_MCU_TTY_CPU" "$main_pid" >/dev/null 2>&1 || true
  log "Widened klipper cgroup to $KLIPPER_CPUS_WIDE, pinned existing threads to CPU $KLIPPER_MCU_TTY_CPU"

  # Compute expected affinity mask for CPU 3 (used for comparison)
  # taskset -p returns hex like "8" for CPU 3
  target_mask=$(printf '%x' $((1 << KLIPPER_MCU_TTY_CPU)))

  log "Starting klipper thread/child monitor for pid $main_pid (poll=${MONITOR_POLL_INTERVAL}s)"

  (
    # Write our PID to the file so we can be killed on re-run
    echo $$ > "$MONITOR_PID_FILE" 2>/dev/null || true

    # Cleanup PID file on exit
    trap 'rm -f "$MONITOR_PID_FILE" 2>/dev/null; exit 0' INT TERM EXIT

    seen_children=""
    thread_check_interval=10  # Only re-check thread affinity every 10 iterations (1 second)
    iteration=0

    while kill -0 "$main_pid" 2>/dev/null; do
      iteration=$((iteration + 1))

      # --- Pin new/migrated threads in main process to CPU 3 ---
      # Only check periodically to reduce overhead (threads don't drift often)
      if [ "$((iteration % thread_check_interval))" = "0" ]; then
        for tid_path in /proc/"$main_pid"/task/*; do
          tid="${tid_path##*/}"
          [ -d "$tid_path" ] || continue
          [ "$tid" != "$main_pid" ] || continue  # Skip main thread (already pinned)

          # Get current affinity via taskset (more reliable than parsing /proc)
          # Output format: "pid 1234's current affinity mask: 8"
          current=$(taskset -p "$tid" 2>/dev/null | sed 's/.*: //' || echo "")

          # Compare masks - only re-pin if different
          if [ -n "$current" ] && [ "$current" != "$target_mask" ]; then
            taskset -pc "$KLIPPER_MCU_TTY_CPU" "$tid" >/dev/null 2>&1 || true
          fi
        done
      fi

      # --- Migrate and demote child processes ---
      child_pids=""

      if [ "$has_children_file" = "1" ]; then
        # Fast path: read from children file
        child_pids=$(cat "$children_file" 2>/dev/null || true)
      else
        # Fallback: find processes whose parent is klipper
        child_pids=$(pgrep -P "$main_pid" 2>/dev/null || true)
      fi

      for cpid in $child_pids; do
        [ -n "$cpid" ] || continue

        # Skip already-seen children
        case " $seen_children " in
          *" $cpid "*) continue ;;
        esac

        # Verify it's a real child process (not a thread)
        if [ -d "/proc/$cpid" ]; then
          # Read Tgid and PPid in one pass for efficiency
          proc_info=$(awk '/^Tgid:|^PPid:/{printf "%s ", $2}' "/proc/$cpid/status" 2>/dev/null || echo "")
          tgid=$(echo "$proc_info" | awk '{print $1}')
          ppid=$(echo "$proc_info" | awk '{print $2}')

          # Must be a process leader (tgid == pid) and child of klipper
          if [ "$tgid" = "$cpid" ] && [ "$ppid" = "$main_pid" ]; then

            # CRITICAL: First demote from inherited SCHED_FIFO to SCHED_OTHER
            # This MUST happen before renice (renice has no effect on RT processes)
            if chrt -o -p 0 "$cpid" >/dev/null 2>&1; then
              logger -t "$TAG" "klipper child $cpid demoted to SCHED_OTHER"
            else
              logger -t "$TAG" "WARN: failed to demote child $cpid from SCHED_FIFO"
            fi

            # Now migrate to MISC_CPU
            if taskset -apc "$MISC_CPU" "$cpid" >/dev/null 2>&1; then
              logger -t "$TAG" "klipper child $cpid -> CPU $MISC_CPU"
            fi

            # Apply nice and ionice (now that it's SCHED_OTHER, these work)
            renice -n 15 -p "$cpid" >/dev/null 2>&1 || true
            ionice -c2 -n 7 -p "$cpid" >/dev/null 2>&1 || true  # best-effort class, low priority

            seen_children="$seen_children $cpid"
          fi
        fi
      done

      # Clean up seen_children list (remove dead processes to prevent unbounded growth)
      if [ "$((iteration % 100))" = "0" ]; then
        new_seen=""
        for cpid in $seen_children; do
          [ -d "/proc/$cpid" ] && new_seen="$new_seen $cpid"
        done
        seen_children="$new_seen"
      fi

      sleep "$MONITOR_POLL_INTERVAL"
    done

    logger -t "$TAG" "klipper monitor exiting (main process gone)"
  ) &

  monitor_pid=$!

  # Pin monitor to MISC_CPU with lowest priority
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

log "klipper-mcu:$(ps_line "$(systemctl show -p MainPID --value klipper-mcu.service 2>/dev/null || echo 0)")"
log "klipper:    $(ps_line "$(systemctl show -p MainPID --value klipper.service 2>/dev/null || echo 0)")"
log "done (IRQs: ttyS0:${IRQ_S0:-?} ttyS1:${IRQ_S1:-?} ttyS2:${IRQ_S2:-?}, multiprocessing=$MULTIPROCESSING_DETECTED)"
exit 0
