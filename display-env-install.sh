#!/bin/bash

# Update system packages and install Python venv
sudo apt update
sudo apt install python3.11-venv -y

# Define project directory
project_dir=~/display_connector

# Create and activate a Python virtual environment
echo "Creating and activating a virtual environment..."
python3 -m venv "$project_dir/venv"
source "$project_dir/venv/bin/activate"

# Install required Python packages
echo "Installing required Python packages..."
pip install -r "$project_dir/requirements.txt"

# Deactivate the virtual environment
echo "Deactivating the virtual environment..."
deactivate

echo "Setup completed."
