#!/bin/bash

sudo rm -rf ~/display_connector/venv
rm -rf ~/display_connector/__pycache__
# Run the first script
~/display_connector/display-env-install.sh

# Define the service file path, script path, and log file path
OLD_SERVICE_FILE="/etc/systemd/system/OpenNept4une.service"
SERVICE_FILE="/etc/systemd/system/display.service"
SCRIPT_PATH="$HOME/display_connector/display.py"
VENV_PATH="$HOME/display_connector/venv"
LOG_FILE="/var/log/display.log"
MOONRAKER_ASVC="$HOME/printer_data/moonraker.asvc"

# Check if the script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: Script $SCRIPT_PATH not found."
    exit 1
fi

# Check if the old service exists and is running
if systemctl is-active --quiet OpenNept4une; then
    # Stop the service silently
    sudo service OpenNept4une stop >/dev/null 2>&1
    # Disable the service silently
    sudo service OpenNept4une disable >/dev/null 2>&1
    sudo rm -f $OLD_SERVICE_FILE
else
    echo "Continuing..."
fi

if systemctl is-active --quiet display; then
    # Stop the service silently
    sudo service display stop >/dev/null 2>&1
else
    echo "Continuing..."
fi

# Create the systemd service file 
echo "Creating systemd service file at $SERVICE_FILE..."
cat <<EOF | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=OpenNept4une TouchScreen Display Service
After=klipper.service klipper-mcu.service moonraker.service
Wants=klipper.service moonraker.service
Documentation=https://github.com/OpenNeptune3D/display_connector

[Service]
Type=simple
User=mks
Group=mks
WorkingDirectory=/home/mks/display_connector
ExecStartPre=/bin/sleep 10
ExecStart=/home/mks/display_connector/venv/bin/python /home/mks/display_connector/display.py

# Restart configuration
Restart=on-failure
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=300

# Timeouts
TimeoutStartSec=60
TimeoutStopSec=30

# Memory limits - 256M max, throttle at 200M
MemoryMax=256M
MemoryHigh=200M
MemorySwapMax=128M

# CPU limits - 25% of one core maximum
CPUQuota=35%
CPUWeight=50
Nice=5

# I/O priority
IOSchedulingClass=2
IOSchedulingPriority=4

# Task/thread limits
TasksMax=200

# File descriptor limits
LimitNOFILE=1024

# Security hardening
ProtectSystem=full
PrivateTmp=true
NoNewPrivileges=true
ProtectKernelTunables=true
ProtectControlGroups=true

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd to read new service file
echo "Reloading systemd..."
sudo systemctl daemon-reload

# Enable and start the service
echo "Enabling and starting the service..."
sudo systemctl enable display.service
sudo systemctl start display.service

echo "Allowing Moonraker to control display service"
grep -qxF 'display' $MOONRAKER_ASVC || echo 'display' >> $MOONRAKER_ASVC

sudo service moonraker restart
