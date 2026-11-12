#!/bin/sh
# Start Nabu (beta) on macOS from this git clone. Linux uses the same steps but is untested.
#
#   1. Checks this machine: macOS on Apple silicon or Intel, memory, free disk, git and Node.
#   2. Installs Nabu from this clone the first time, and again whenever the clone changed
#      (git pull, local edits): builds the review window and the release, then runs
#      install/install.sh. That installer asks once before it downloads Ollama or a model and
#      shows the sizes first.
#   3. Every start: starts Ollama if it is stopped and checks that the set-up model is
#      installed. If not, it runs the model setup again (which asks before downloading).
#   4. Opens the review window. Nabu runs until "Quit Nabu" in the window or Ctrl+C here.
#
# usage: sh start-nabu.sh [--setup] [--reinstall] [--model NAME|none] [--no-launch]
#   --setup      run the Ollama and model setup again (e.g. to add a model after "no")
#   --reinstall  rebuild and reinstall Nabu even if the clone did not change
#   --model      a model name instead of the recommended one, or "none"
#   --no-launch  set everything up, but do not open Nabu
set -eu

SETUP=0; REINSTALL=0; MODEL=auto; LAUNCH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --setup) SETUP=1 ;;
    --reinstall) REINSTALL=1 ;;
    --model) shift; MODEL="$1" ;;
    --no-launch) LAUNCH=0 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "start-nabu: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

MIN_NODE=20
MIN_FREE_GB=3  # Nabu itself (about 0.4 GB) plus room; the installer checks model space itself

say() { printf '%s\n' "$*"; }
head_() { printf '\n== %s\n' "$*"; }
fail() { printf 'start-nabu: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
run() { what=$1; shift; printf '  $ %s\n' "$*"; "$@" || fail "$what failed. See the messages above."; }
sha256() { if have sha256sum; then sha256sum | cut -c1-12; else shasum -a 256 | cut -c1-12; fi; }

REPO=$(cd "$(dirname "$0")" && pwd)
SYSTEM=$(uname -s)
if [ "$SYSTEM" = Darwin ]; then
  ROOT="$HOME/Library/Application Support/Nabu App"
else
  ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nabu-app"
fi
APP="$ROOT/app"
PY="$APP/bin/python"
UV="$ROOT/uv/uv"
MARKER="$APP/nabu-source.txt"  # which clone state is installed
RELEASE="$REPO/dist/release"

# ------------------------------------------------------------------ 1. This machine
head_ "Checking this machine"
ARCH=$(uname -m)
case "$SYSTEM-$ARCH" in
  Darwin-arm64|Darwin-x86_64)
    OS_NAME="macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
    RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 )) ;;
  Linux-x86_64|Linux-aarch64|Linux-arm64)
    OS_NAME="Linux (untested beta)"
    RAM_GB=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1048576 )) ;;
  *) fail "Nabu does not support $SYSTEM $ARCH." ;;
esac
FREE_GB=$(( $(df -Pk "$HOME" | awk 'NR==2 {print $4}') / 1048576 ))
say "  $OS_NAME, $ARCH; memory $RAM_GB GB; free in your home folder: $FREE_GB GB"
[ "$FREE_GB" -ge $MIN_FREE_GB ] || fail "Only $FREE_GB GB free. Free at least $MIN_FREE_GB GB (more for a model) and run again."
if [ "$RAM_GB" -lt 8 ]; then
  say "  Note: under 8 GB memory. Nabu will offer no model (digital files and templates only) or the smallest one."
fi

# ------------------------------------------------------------------ 2. Install or update Nabu
SOURCE=unknown
if have git && HEAD_SHA=$(git -C "$REPO" rev-parse HEAD 2>/dev/null); then
  SOURCE=$HEAD_SHA
  if [ -n "$(git -C "$REPO" diff HEAD -- . ':(exclude)tasks' 2>/dev/null | head -c 1)" ]; then
    SOURCE="$SOURCE+local-$(git -C "$REPO" diff HEAD -- . ':(exclude)tasks' 2>/dev/null | sha256)"
  fi
else
  say "  git not found: Nabu is installed once and only updated with --reinstall."
fi
HAVE=""
[ -f "$MARKER" ] && HAVE=$(cat "$MARKER")
NEED_BUILD=0
if [ $REINSTALL = 1 ] || [ ! -x "$PY" ] || [ -z "$HAVE" ]; then NEED_BUILD=1
elif [ "$SOURCE" != unknown ] && [ "$HAVE" != "$SOURCE" ]; then NEED_BUILD=1
fi

JUST_INSTALLED=0
if [ $NEED_BUILD = 1 ]; then
  if [ -x "$PY" ]; then head_ "Updating Nabu from this clone ($SOURCE)"; else head_ "Installing Nabu from this clone"; fi

  have node && have npm || fail "Node.js $MIN_NODE or newer is needed to build Nabu's window. Install the LTS version from https://nodejs.org, open a new terminal, and run this script again."
  NODE_VER=$(node --version)
  NODE_MAJOR=$(printf '%s' "$NODE_VER" | sed -n 's/^v\([0-9][0-9]*\)\..*/\1/p')
  [ -n "$NODE_MAJOR" ] && [ "$NODE_MAJOR" -ge $MIN_NODE ] || \
    fail "Node.js $MIN_NODE or newer is needed (found $NODE_VER). Install the LTS version from https://nodejs.org and run again."
  say "  Node $NODE_VER"

  # Pinned uv (checksum checked), from the same pins as the installer.
  sh "$REPO/install/install.sh" --uv-only || fail "could not set up uv (see above)."

  (cd "$REPO/ui" && run "Installing the window's build tools (npm ci)" npm ci --no-audit --no-fund \
     && run "Building the review window" npm run build) || exit 1

  export UV_PYTHON_INSTALL_DIR="$ROOT/python"
  run "Building the release" "$UV" run --no-project --python 3.12 "$REPO/install/build_release.py" \
    --uv "$UV" --out "$RELEASE"

  head_ "Running the installer"
  sh "$RELEASE/install.sh" --model "$MODEL" || \
    fail "the installer reported problems (listed above). Fix them and run this script again; finished steps are not repeated."
  if [ "$SOURCE" != unknown ] || [ -z "$HAVE" ]; then printf '%s\n' "$SOURCE" > "$MARKER"; fi
  JUST_INSTALLED=1
fi

# ------------------------------------------------------------------ 3. Ollama and the model
if [ $JUST_INSTALLED = 0 ]; then
  if [ $SETUP = 1 ]; then
    head_ "Setting up Ollama and the model again"
    "$PY" -m nabu.install --model "$MODEL" || fail "the setup reported problems (listed above). Fix them and run again."
  else
    head_ "Checking Ollama and the model"
    RC=0; "$PY" -m nabu.install --check || RC=$?
    if [ $RC = 3 ]; then
      say "  Running the model setup (it asks before downloading anything)."
      "$PY" -m nabu.install --model "$MODEL" || \
        say "  The setup reported problems (above). Nabu opens anyway; reads that need a model will say so."
    elif [ $RC != 0 ]; then
      fail "the check failed (exit $RC). See the message above."
    fi
  fi
fi

# ------------------------------------------------------------------ 4. Open Nabu
if [ $LAUNCH = 0 ]; then
  say ""; say "Ready. Start Nabu with this script or the Nabu app in your Applications folder."; exit 0
fi
head_ "Opening Nabu"
say "  The review window opens in your browser. Stop Nabu with 'Quit Nabu' in the window, or Ctrl+C here."
exec "$PY" -m nabu.app
