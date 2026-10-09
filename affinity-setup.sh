#!/bin/sh
# Retired affinity helper: one-time cleanup of the legacy affinity.service.
#
# Earlier versions pinned Klipper/IRQs to CPUs, ran klippy and klipper-mcu at
# SCHED_FIFO 60 and disabled RT throttling, which could starve Klipper's serial
# thread (OpenNept4une#445). This removes the unit, its enable symlinks, the old
# /usr/local/sbin copy and any runtime unit properties it set. Runtime scheduling
# changes already applied to running processes clear on the next reboot.
# CPU governor policy is owned by the image (/etc/default/cpufrequtils).

TAG="display-affinity-cleanup"

log() {
  logger -t "$TAG" -- "$@" 2>/dev/null || true
  printf '%s: %s\n' "$TAG" "$*"
}

# Re-exec as root when run from the installer as a normal user.
if [ "$(id -u)" != 0 ]; then
  exec sudo -E -- "$0" "$@"
fi

systemctl disable affinity.service >/dev/null 2>&1 || true
# Older units were also WantedBy klipper, klipper-mcu and multi-user.target.
find /etc/systemd/system -path '*.wants/affinity.service' -delete 2>/dev/null || true
rm -f /etc/systemd/system/affinity.service /usr/local/sbin/affinity-setup.sh

# Drop runtime properties set via 'systemctl set-property --runtime'.
for prop in AllowedCPUs CPUSchedulingPolicy CPUSchedulingPriority; do
  rm -f /run/systemd/system.control/*.service.d/50-"$prop".conf
done

systemctl daemon-reload >/dev/null 2>&1 || true
log "Removed legacy affinity.service; reboot to clear any leftover realtime scheduling"

exit 0
