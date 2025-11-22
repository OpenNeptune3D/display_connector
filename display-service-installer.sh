#!/bin/bash
set -euo pipefail

# --- Paths/constants -------------------------------------------------------
OLD_SERVICE_FILE="/etc/systemd/system/OpenNept4une.service"
DISPLAY_SERVICE_FILE="/etc/systemd/system/display.service"
AFFINITY_SERVICE_FILE="/etc/systemd/system/affinity.service"
AFFINITY_SCRIPT_PATH="/usr/local/sbin/affinity-setup.sh"

DISPLAY_CONNECTOR_PATH="$HOME/display_connector"
SCRIPT_PATH="$DISPLAY_CONNECTOR_PATH/display.py"
ENV_INSTALLER="$DISPLAY_CONNECTOR_PATH/display-env-install.sh"
VENV_DIR="$DISPLAY_CONNECTOR_PATH/venv"
PYCACHE_DIR="$DISPLAY_CONNECTOR_PATH/__pycache__"

MOONRAKER_ASVC="$HOME/printer_data/moonraker.asvc"

# --- Preflight ---------------------------------------------------------------
# fail clearly if source files are missing.
[ -f "$SCRIPT_PATH" ] || { echo "Error: $SCRIPT_PATH not found."; exit 1; }
[ -f "$ENV_INSTALLER" ] || { echo "Error: $ENV_INSTALLER not found."; exit 1; }
[ -f "$DISPLAY_CONNECTOR_PATH/display.service" ] || { echo "Error: display.service not found in $DISPLAY_CONNECTOR_PATH"; exit 1; }
[ -f "$DISPLAY_CONNECTOR_PATH/affinity.service" ] || { echo "Error: affinity.service not found in $DISPLAY_CONNECTOR_PATH"; exit 1; }
[ -f "$DISPLAY_CONNECTOR_PATH/affinity-setup.sh" ] || { echo "Error: affinity-setup.sh not found in $DISPLAY_CONNECTOR_PATH"; exit 1; }

# --- Stop display early (avoid venv race) ------------------------------------
if systemctl is-active --quiet display.service; then
  sudo systemctl stop display.service >/dev/null 2>&1 || true
fi

# --- Rebuild environment -----------------------------------------------------
# keep $HOME clean;
rm -rf "$VENV_DIR" "$PYCACHE_DIR"
bash "$ENV_INSTALLER"

# --- Legacy unit cleanup -----------------------------------------------------
if systemctl list-unit-files | grep -q '^OpenNept4une\.service'; then
  sudo systemctl disable --now OpenNept4une.service || true
fi
[ -e "$OLD_SERVICE_FILE" ] && sudo rm -f "$OLD_SERVICE_FILE"

# --- Enable Performance CPU --------------------------------------------------
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# --- Install units and script ------------------------------------------------
echo "Installing display.service to $DISPLAY_SERVICE_FILE"
sudo cp "$DISPLAY_CONNECTOR_PATH/display.service" "$DISPLAY_SERVICE_FILE" >/dev/null

echo "Installing affinity-setup.sh to $AFFINITY_SCRIPT_PATH"
sudo cp "$DISPLAY_CONNECTOR_PATH/affinity-setup.sh" "$AFFINITY_SCRIPT_PATH" >/dev/null
sudo chmod +x "$AFFINITY_SCRIPT_PATH" >/dev/null

echo "Installing affinity.service to $AFFINITY_SERVICE_FILE"
sudo cp "$DISPLAY_CONNECTOR_PATH/affinity.service" "$AFFINITY_SERVICE_FILE" >/dev/null

# --- Reload systemd ----------------------------------------------------------
echo "Reloading systemd units..."
sudo systemctl daemon-reload

# --- Enable + start services -------------------------------------------------
echo "Enabling and starting affinity.service..."
sudo systemctl enable affinity.service
sudo systemctl start affinity.service

echo "Enabling and starting display.service..."
sudo systemctl enable display.service
sudo systemctl start display.service

# --- Moonraker allowlist update ----------------------------------------------
# Now Handled by OpenNept4unes install_configs functoin
#echo "Allowing Moonraker to control display service..."
#sudo touch "$MOONRAKER_ASVC"
#grep -qxF 'display' "$MOONRAKER_ASVC" || echo 'display' | sudo tee -a "$MOONRAKER_ASVC" >/dev/null

# --- Restart Moonraker -------------------------------------------------------
sudo systemctl restart moonraker

echo "Done."
