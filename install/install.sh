#!/bin/sh
# Install Nabu for this user on Linux or macOS (FR-1.2). No root needed.
#
# Run from the release folder, which holds this script, the nabu wheel, requirements.txt and
# SHA256SUMS. Same steps as install.ps1:
#   1. check every release file against SHA256SUMS;
#   2. get uv (pinned version, checksum checked);
#   3. create Nabu's own Python environment and install the hash-pinned requirements and wheel;
#   4. hand over to `python -m nabu.install` (runtime, model, OCR packs, config, shortcut,
#      test read), which asks before every download.
# Running it again changes nothing already in place and downloads nothing.
#
# usage: sh install.sh [--dry-run] [--yes] [--model NAME|none] [--no-shortcut]
set -eu

UV_VERSION=0.12.19
PYTHON_VERSION=3.12

DRY_RUN=0
PASS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; PASS="$PASS --dry-run" ;;
    --yes) PASS="$PASS --yes" ;;
    --no-shortcut) PASS="$PASS --no-shortcut" ;;
    --model) shift; PASS="$PASS --model $1" ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "nabu install: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
fail() { printf 'nabu install: %s\n' "$*" >&2; exit 1; }
show() { printf '  $ %s\n' "$*"; }
run() { show "$@"; "$@" || fail "the command above failed"; }

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) UV_FILE=uv-x86_64-unknown-linux-gnu.tar.gz
    UV_SHA=23bf5552d220e0842b65c862097b2ebaeba0064b74eda5e565e77fd25969d8c8 ;;
  Linux-aarch64|Linux-arm64) UV_FILE=uv-aarch64-unknown-linux-gnu.tar.gz
    UV_SHA=0804e9b164c64b6914182d5920c08551958a095986f10a3731056df701126436 ;;
  Darwin-x86_64) UV_FILE=uv-x86_64-apple-darwin.tar.gz
    UV_SHA=cb5fa57bafe68fc0fb94b17f06bee0b0b9a7feb94ccbd110445afa0696e39273 ;;
  Darwin-arm64) UV_FILE=uv-aarch64-apple-darwin.tar.gz
    UV_SHA=a9a8df1eedeb192f2e47e40e2faabfb387db4b850209118786d42f89dde3e0ba ;;
  *) fail "no release for $(uname -s) $(uname -m)" ;;
esac
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$UV_FILE"

if [ "$(uname -s)" = Darwin ]; then
  ROOT="$HOME/Library/Application Support/Nabu App"
else
  ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nabu-app"
fi
UV_DIR="$ROOT/uv"
UV="$UV_DIR/uv"
APP="$ROOT/app"
PY="$APP/bin/python"
HERE=$(cd "$(dirname "$0")" && pwd)

# 1. Release files (FR-1.12)
[ -f "$HERE/SHA256SUMS" ] || fail "SHA256SUMS is missing next to install.sh"
WHEEL=""
while read -r want name; do
  name=${name#\*}
  [ -n "$name" ] || continue
  [ -f "$HERE/$name" ] || fail "$name is listed in SHA256SUMS but missing"
  [ "$(sha256 "$HERE/$name")" = "$want" ] || \
    fail "$name does not match its checksum in SHA256SUMS; the release folder is damaged"
  case "$name" in nabu-*.whl) WHEEL="$HERE/$name" ;; esac
done < "$HERE/SHA256SUMS"
[ -n "$WHEEL" ] || fail "no nabu wheel listed in SHA256SUMS"
REQ="$HERE/requirements.txt"
say "Release files checked against SHA256SUMS."

# 2. uv
if [ -x "$UV" ] && "$UV" --version 2>/dev/null | grep -q "$UV_VERSION"; then
  say "uv $UV_VERSION already in place: $UV"
elif [ $DRY_RUN = 1 ]; then
  say "Would download uv $UV_VERSION ($UV_URL), check sha256 $UV_SHA, unpack to $UV_DIR"
else
  mkdir -p "$UV_DIR"
  TMP=$(mktemp -d)
  say "Downloading uv $UV_VERSION"
  curl -fsSL "$UV_URL" -o "$TMP/$UV_FILE" || fail "could not download uv; check the internet connection"
  if [ "$(sha256 "$TMP/$UV_FILE")" != "$UV_SHA" ]; then
    rm -rf "$TMP"
    fail "$UV_FILE does not match the checksum shipped with Nabu; it was deleted and nothing was installed"
  fi
  tar -xzf "$TMP/$UV_FILE" -C "$TMP"
  cp "$TMP"/uv-*/uv "$UV"
  rm -rf "$TMP"
  say "uv $UV_VERSION installed: $UV"
fi

# 3. Nabu's own Python environment
export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export UV_NO_CACHE=1  # nothing reuses a cache: a re-run skips installed steps
WHEEL_VERSION=$(basename "$WHEEL" | cut -d- -f2)
WHEEL_SHA=$(sha256 "$WHEEL")
MARKER="$APP/nabu-wheel.sha256"  # which wheel is installed; the same version can differ
if [ -x "$PY" ] && [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$WHEEL_SHA" ]; then
  say "Nabu $WHEEL_VERSION already installed: $APP"
elif [ $DRY_RUN = 1 ]; then
  say "Would create $APP with Python $PYTHON_VERSION and install:"
  show "$UV" venv "$APP" --python $PYTHON_VERSION
  show "$UV" pip install --python "$PY" --require-hashes -r "$REQ"
  show "$UV" pip install --python "$PY" --no-deps "$WHEEL"
else
  [ -x "$PY" ] || run "$UV" venv "$APP" --python $PYTHON_VERSION
  run "$UV" pip install --python "$PY" --require-hashes -r "$REQ"
  run "$UV" pip install --python "$PY" --no-deps --reinstall-package nabu "$WHEEL"
  echo "$WHEEL_SHA" > "$MARKER"
  say "Nabu $WHEEL_VERSION installed: $APP"
fi

# 4. Runtime, model, OCR packs, config, shortcut, test read
if [ ! -x "$PY" ]; then
  say ""
  say "Dry run: Nabu is not installed yet, so the model and OCR plan is printed after the real install."
  say "Dry run: nothing was changed."
  exit 0
fi
say ""
# shellcheck disable=SC2086  # PASS holds separate flags
exec "$PY" -m nabu.install $PASS
