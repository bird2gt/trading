#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
DEFAULT_MT4_ROOT="$HOME/Library/Application Support/net.metaquotes.wine.metatrader4/drive_c/Program Files (x86)/MetaTrader 4"
MT4_ROOT="${MT4_ROOT:-$DEFAULT_MT4_ROOT}"
SRC="$ROOT/mt4/SignalBridge.mq4"
EXPERTS_DIR="$MT4_ROOT/MQL4/Experts"
DST="$EXPERTS_DIR/SignalBridge.mq4"
METAEDITOR="$MT4_ROOT/metaeditor.exe"
COMPILE_LOG="$EXPERTS_DIR/SignalBridge.compile.log"

usage() {
  cat <<'USAGE'
Usage:
  scripts/install_signalbridge_mt4.sh [--check] [--no-compile]

Environment:
  MT4_ROOT=/path/to/MetaTrader 4
  WINE=/path/to/wine

Actions:
  --check       compare project and installed SignalBridge.mq4 without writing
  --no-compile  copy source only, skip MetaEditor compile attempt
USAGE
}

CHECK_ONLY=0
NO_COMPILE=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --no-compile) NO_COMPILE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 2 ;;
  esac
done

if [[ ! -f "$SRC" ]]; then
  echo "Source file not found: $SRC" >&2
  exit 1
fi

# Hash with line endings normalized (strip CR) so CRLF vs LF drift — MT4 may
# rewrite the installed file as CRLF — doesn't trigger a spurious reinstall.
content_hash() { /usr/bin/tr -d '\r' < "$1" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}'; }

source_hash="$(content_hash "$SRC")"
installed_hash=""
if [[ -f "$DST" ]]; then
  installed_hash="$(content_hash "$DST")"
fi

echo "Project source:   $SRC"
echo "Installed target: $DST"
echo "Project SHA256:   $source_hash"
echo "Installed SHA256: ${installed_hash:-missing}"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  if [[ "$source_hash" == "$installed_hash" ]]; then
    echo "OK: installed SignalBridge.mq4 matches project source."
    exit 0
  fi
  echo "MISMATCH: installed SignalBridge.mq4 does not match project source."
  exit 1
fi

/bin/mkdir -p "$EXPERTS_DIR"

if [[ -f "$DST" && "$source_hash" != "$installed_hash" ]]; then
  backup="$DST.backup.$(/bin/date -u '+%Y%m%d%H%M%S')"
  /bin/cp "$DST" "$backup"
  echo "Backup created: $backup"
fi

/bin/cp "$SRC" "$DST"
echo "Installed source updated."

if [[ "$NO_COMPILE" -eq 1 ]]; then
  echo "Compile skipped by --no-compile."
  exit 0
fi

if [[ ! -f "$METAEDITOR" ]]; then
  echo "MetaEditor not found: $METAEDITOR"
  echo "Source was copied; compile SignalBridge.mq4 in MetaEditor before relying on the EA."
  exit 0
fi

wine_bin=""
if [[ -n "${WINE:-}" && -x "$WINE" ]]; then
  wine_bin="$WINE"
elif command -v wine >/dev/null 2>&1; then
  wine_bin="$(command -v wine)"
elif command -v wine64 >/dev/null 2>&1; then
  wine_bin="$(command -v wine64)"
else
  # MetaTrader.app ships its own wine; use it when nothing is on PATH.
  for bundled in \
    "/Applications/MetaTrader 4.app/Contents/SharedSupport/wine/bin/wine64" \
    "/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64"; do
    if [[ -x "$bundled" ]]; then
      wine_bin="$bundled"
      break
    fi
  done
fi

if [[ -z "$wine_bin" ]]; then
  echo "Wine executable not found in PATH."
  echo "Source was copied; compile SignalBridge.mq4 in MetaEditor before relying on the EA."
  exit 0
fi

echo "Compiling with: $wine_bin"
# MetaEditor under wine rejects absolute unix paths in /compile; pass a
# windows-relative path and run from MT4_ROOT so it resolves against drive_c.
# WINEPREFIX is the parent of drive_c (e.g. .../net.metaquotes.wine.metatrader4).
compile_src='MQL4\Experts\SignalBridge.mq4'
# WINEPREFIX is the dir containing drive_c; MT4_ROOT is <prefix>/drive_c/Program Files (x86)/MetaTrader 4.
wine_prefix="${WINEPREFIX:-${MT4_ROOT%/drive_c/*}}"
( cd "$MT4_ROOT" && WINEPREFIX="$wine_prefix" WINEDEBUG="${WINEDEBUG:--all}" \
  "$wine_bin" "$METAEDITOR" "/compile:$compile_src" "/log:$COMPILE_LOG" ) || true

if [[ -f "$COMPILE_LOG" ]]; then
  echo "Compile log: $COMPILE_LOG"
  /usr/bin/tail -40 "$COMPILE_LOG"
fi

ex4="$EXPERTS_DIR/SignalBridge.ex4"
if [[ -f "$ex4" && "$ex4" -nt "$DST" ]]; then
  echo "OK: compiled EX4 is newer than source."
  exit 0
fi

echo "Compile result could not be confirmed. Check MetaEditor log and restart/reload the EA."
exit 1
