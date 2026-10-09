#!/bin/sh
# Sperrt die Messumgebung für Release 0.4.0 in eval/requirements.lock.
#   sh eval/make_lock.sh
# Legt die frische venv eval/work/lock-venv mit Python 3.13 an, installiert
# das lokale Paket mit den acht Pins aus eval/requirements.txt und friert die
# Kette ein. Lädt torch (groß); deshalb startet Klaus dieses Skript selbst.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$ROOT/eval/work/lock-venv"
PYTHON=${PYTHON:-python3.13}
LOCK="$ROOT/eval/requirements.lock"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON nicht gefunden (Messumgebung braucht Python 3.13)" >&2
    exit 1
fi
if [ -e "$VENV" ]; then
    echo "error: $VENV existiert bereits; bitte löschen und erneut starten" >&2
    exit 1
fi
TMP=$(mktemp "${LOCK%/*}/requirements.lock.XXXXXX")
trap 'rm -f "$TMP"' EXIT
"$PYTHON" -m venv "$VENV"
if [ "$("$VENV/bin/python" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')")" != "3.13" ]; then
    echo "error: venv meldet kein Python 3.13" >&2
    exit 1
fi
cd "$ROOT"
"$VENV/bin/pip" install -e . -r eval/requirements.txt
{
    echo "# Messumgebung für TEI CRM Bridge 0.4.0 - erzeugt von 'sh eval/make_lock.sh', nicht von Hand ändern."
    echo "# python: $("$VENV/bin/python" -c "import sys; print(sys.version)")"
    echo "# os/arch: $("$VENV/bin/python" -c "import platform; print(platform.platform(), '/', platform.machine())")"
    echo "# date (UTC): $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "# command: pip install -e . -r eval/requirements.txt"
    echo "# freeze: pip freeze --exclude-editable"
    "$VENV/bin/pip" freeze --exclude-editable
} > "$TMP"
mv "$TMP" "$LOCK"
echo "lockfile written to $LOCK"
