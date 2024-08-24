#!/bin/bash

SCRIPT=$(realpath "$0")
SCRIPTPATH=$(dirname "$SCRIPT")

OLD_SERVICE_FILE="/etc/systemd/system/OpenNept4une.service"
SERVICE_FILE="/etc/systemd/system/display.service"
SCRIPT_PATH="$SCRIPTPATH/display.py"
VENV_PATH="$SCRIPTPATH/venv"
LOG_FILE="/var/log/display.log"
MOONRAKER_ASVC="$HOME/printer_data/moonraker.asvc"

R=$'\e[1;91m'    # Red ${R}
G=$'\e[1;92m'    # Green ${G}
Y=$'\e[1;93m'    # Yellow ${Y}
M=$'\e[1;95m'    # Magenta ${M}
C=$'\e[96m'      # Cyan ${C}
NC=$'\e[0m'      # No Color ${NC}

reset_env() {
    sudo rm -rf "$SCRIPTPATH/venv"
    rm -rf "$SCRIPTPATH/__pycache__"
}

install_env() {
    sudo apt update
    sudo apt install python3-venv -y

    # Create and activate a Python virtual environment
    echo "Creating and activating a virtual environment..."
    python3 -m venv "$SCRIPTPATH/venv"
    source "$SCRIPTPATH/venv/bin/activate"

    # Install required Python packages
    echo "Installing required Python packages..."
    pip install -r "$SCRIPTPATH/requirements.txt"

    # Deactivate the virtual environment
    echo "Deactivating the virtual environment..."
    deactivate

    echo "Environment setup completed."
}

stop_service() {
    if systemctl is-active --quiet OpenNept4une; then
        # Stop the service silently
        sudo service OpenNept4une stop >/dev/null 2>&1
        # Disable the service silently
        sudo service OpenNept4une disable >/dev/null 2>&1
        sudo rm -f $OLD_SERVICE_FILE
    fi

    if systemctl is-active --quiet display; then
        # Stop the service silently
        sudo service display stop >/dev/null 2>&1
    fi
}

disable_service() {
    echo "Disabling the service..."
    sudo systemctl disable display.service
}

create_service() {
    # Create the systemd service file 
    echo "Creating systemd service file at $SERVICE_FILE..."
    cat <<EOF | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=OpenNept4une TouchScreen Display Service
After=klipper.service klipper-mcu.service moonraker.service
Wants=klipper.service moonraker.service
Documentation=man:display(8)

[Service]
ExecStartPre=/bin/sleep 10
ExecStart=$SCRIPTPATH/venv/bin/python $SCRIPTPATH/display.py
WorkingDirectory=$SCRIPTPATH
Restart=on-failure
RestartSec=10
User=$USER
ProtectSystem=full
PrivateTmp=true

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
}

give_moonraker_control() {
    echo "Allowing Moonraker to control display service"
    grep -qxF 'display' $MOONRAKER_ASVC || echo 'display' >> $MOONRAKER_ASVC

    sudo service moonraker restart
}

moonraker_update_manager() {
    update_selection="display"
    config_file="$HOME/printer_data/config/moonraker.conf"

    if [ "$update_selection" = "OpenNept4une" ]; then
        new_lines="[update_manager $update_selection]\n\
type: git_repo\n\
primary_branch: $current_branch\n\
path: $OPENNEPT4UNE_DIR\n\
is_system_service: False\n\
origin: $OPENNEPT4UNE_REPO"

    elif [ "$update_selection" = "display" ]; then
        current_display_branch=$(git -C "$DISPLAY_CONNECTOR_DIR" symbolic-ref --short HEAD 2>/dev/null)
        new_lines="[update_manager $update_selection]\n\
type: git_repo\n\
primary_branch: $current_display_branch\n\
path: $DISPLAY_CONNECTOR_DIR\n\
virtualenv: $DISPLAY_CONNECTOR_DIR/venv\n\
requirements: requirements.txt\n\
origin: $DISPLAY_CONNECTOR_REPO"
    else
        echo -e "${R}Invalid argument. Please specify either 'OpenNept4une' or 'display_connector'.${NC}"
        return 1
    fi
    # Check if the lines exist in the config file
    if grep -qF "[update_manager $update_selection]" "$config_file"; then
        # Lines exist, update them
        perl -pi.bak -e "BEGIN{undef $/;} s|\[update_manager $update_selection\].*?((?:\r*\n){2}\|$)|$new_lines\$1|gs" "$config_file"
        sync
    else
        # Lines do not exist, append them to the end of the file
        echo -e "\n$new_lines" >> "$config_file"
    fi
}

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "${R}Error: Script $SCRIPT_PATH not found.${NC}"
    exit 1
fi

HELP="Please specify either 'full', 'env', 'service-install', 'service-disable' or 'moonraker'."

if [ "$1" ]; then
    case "$1" in
        "full")
            reset_env
            install_env
            stop_service
            create_service
            give_moonraker_control
            ;;
        "env")
            reset_env
            install_env
            ;;
        "service-install")
            stop_service
            create_service
            ;;
        "service-disable")
            stop_service
            disable_service
            ;;
        "moonraker")
            give_moonraker_control
            moonraker_update_manager
            ;;
        *)
            echo "${R}Invalid argument $1. ${Y}$HELP${NC}"
            exit 1
            ;;
    esac
else
    echo "${R}No arguments provided. ${Y}$HELP${NC}"
    exit 1
fi
