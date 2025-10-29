#!/bin/bash

# Update system packages and install Python venv
sudo apt update

# Try to install python3.13-venv first, fall back to python3.11-venv
if sudo apt-cache show python3.13-venv >/dev/null 2>&1; then
    echo "Installing python3.13-venv..."
    sudo apt install python3.13-venv -y
    PYTHON_CMD=python3.13
elif sudo apt-cache show python3.11-venv >/dev/null 2>&1; then
    echo "Installing python3.11-venv..."
    sudo apt install python3.11-venv -y
    PYTHON_CMD=python3.11
else
    echo "Neither python3.13-venv nor python3.11-venv is available. Using default python3..."
    sudo apt install python3-venv -y
    PYTHON_CMD=python3
fi

# Define project directory
project_dir=~/display_connector

# Create and activate a Python virtual environment
echo "Creating and activating a virtual environment..."
$PYTHON_CMD -m venv "$project_dir/venv"
source "$project_dir/venv/bin/activate"

# Install required Python packages
echo "Installing required Python packages..."
pip install -r "$project_dir/requirements.txt"

# Deactivate the virtual environment
echo "Deactivating the virtual environment..."
deactivate

echo "Setup completed."
