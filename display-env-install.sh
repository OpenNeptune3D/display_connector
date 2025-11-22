#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# --- Config -------------------------------------------------------------------
PROJECT_DIR="${PROJECT_DIR:-$HOME/display_connector}"
VENV_DIR="$PROJECT_DIR/venv"
REQ_FILE="$PROJECT_DIR/requirements.txt"

# --- Preflight ----------------------------------------------------------------
[ -d "$PROJECT_DIR" ] || { echo "Error: project directory $PROJECT_DIR not found"; exit 1; }
[ -f "$REQ_FILE" ]    || { echo "Error: requirements file $REQ_FILE not found"; exit 1; }

# --- System packages (lightweight) -------------------------------------------
echo "[1/6] Updating APT and installing minimal prereqs..."
sudo apt-get update
sudo apt-get install -y libsystemd-dev setserial

# --- Python / venv selection --------------------------------------------------
# Prefer 3.13, then 3.12, then 3.11, else system default python3-venv.
choose_python() {
  local pkg cmd
  if apt-cache show python3.13-venv 2>/dev/null | grep -q '^Version:'; then
    pkg="python3.13-venv"; cmd="python3.13"
  elif apt-cache show python3.12-venv 2>/dev/null | grep -q '^Version:'; then
    pkg="python3.12-venv"; cmd="python3.12"
  elif apt-cache show python3.11-venv 2>/dev/null | grep -q '^Version:'; then
    pkg="python3.11-venv"; cmd="python3.11"
  else
    pkg="python3-venv"; cmd="python3"
  fi
  echo "$pkg|$cmd"
}

echo "[2/6] Selecting Python interpreter..."
read -r VENV_PKG PYTHON_CMD < <(choose_python | tr '|' ' ')
echo "Using $PYTHON_CMD (installing $VENV_PKG)..."
sudo apt-get install -y "$VENV_PKG"

command -v "$PYTHON_CMD" >/dev/null || {
  echo "Error: $PYTHON_CMD not found after installing $VENV_PKG"
  exit 1
}
echo "System Python: $("$PYTHON_CMD" -V)"

# --- venv creation/upgrade --------------------------------------------------
echo "[3/6] Creating/upgrading venv at $VENV_DIR..."
"$PYTHON_CMD" -m venv --upgrade-deps "$VENV_DIR"

PY_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
[ -x "$PY_BIN" ]  || { echo "Error: $PY_BIN not found"; exit 1; }
[ -x "$PIP_BIN" ] || { echo "Error: $PIP_BIN not found"; exit 1; }

echo "Venv Python: $("$PY_BIN" -V)"

echo "[4/6] Upgrading pip/setuptools/wheel..."
"$PIP_BIN" install -U pip setuptools wheel

# --- Dependency installation --------------------------------------------------
echo "[5/6] Installing project requirements (wheel-first)..."
if ! "$PIP_BIN" install --prefer-binary -r "$REQ_FILE"; then
  echo "-> Wheel-first install failed; enabling fallback to source builds."
  echo "-> Installing minimal build deps (one-time, small):"

  # Generic build toolchain + headers commonly needed for Pillow/systemd-python
  sudo apt-get install -y build-essential python3-dev pkg-config \
                          libjpeg-dev zlib1g-dev libfreetype-dev \
                          libopenjp2-7-dev libtiff-dev

  echo "-> Retrying dependency install (no cache, may compile on ARM)..."
  "$PIP_BIN" install --no-cache-dir -r "$REQ_FILE"
fi

# --- Done ---------------------------------------------------------------------
echo "[6/6] Environment ready."
echo "Python: $("$PY_BIN" -V)"
echo "pip:    $("$PIP_BIN" --version)"
echo "Selected packages (if installed):"
"$PIP_BIN" list | grep -E '^(pyserial|pyserial-asyncio|aiohttp|pillow|numpy|systemd-python)\b' || true

echo "Setup completed."
