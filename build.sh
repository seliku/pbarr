#!/bin/bash
#
# Baut das Abbild und veroeffentlicht es.
#
# Warum es dieses Skript gibt: das Dockerfile hat `ARG VERSION=0.0.0-dev`. Wer
# ohne --build-arg baut, bekommt ein Abbild, das sich selbst "0.0.0-dev" nennt.
# Die Aktualisierungspruefung vergleicht diesen Wert mit der neuesten Marke auf
# GitHub - mit 0.0.0-dev haelt sich jede Fassung fuer veraltet. Genau das ist
# bei v1.1.1 und beim ersten Bau von v1.1.2 passiert.
#
# Aufruf:
#   ./build.sh            baut aus der aktuellen Git-Marke, veroeffentlicht nichts
#   ./build.sh --push     veroeffentlicht zusaetzlich als :stable :latest :beta
#   ./build.sh --push 1.2.0   nimmt diese Version statt der Git-Marke

set -euo pipefail

REGISTRY="ghcr.io/seliku/pbarr"
PUSH=0
VERSION=""

for arg in "$@"; do
    case "$arg" in
        --push) PUSH=1 ;;
        -*)     echo "Unbekannte Option: $arg" >&2; exit 1 ;;
        *)      VERSION="$arg" ;;
    esac
done

# Version aus der Git-Marke ableiten, wenn keine angegeben wurde.
if [ -z "$VERSION" ]; then
    VERSION=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//') || true
    if [ -z "$VERSION" ]; then
        echo "Keine Git-Marke gefunden. Version als Argument angeben." >&2
        exit 1
    fi
fi

# Nur Ziffern und Punkte - sonst scheitert der Versionsvergleich zur Laufzeit.
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    echo "Version '$VERSION' sieht nicht nach x.y.z aus." >&2
    exit 1
fi

# Nicht aus einem schmutzigen Arbeitsbaum veroeffentlichen: das Abbild truege
# eine Versionsnummer, zu der es keinen Stand im Verlauf gibt.
if [ "$PUSH" = "1" ] && [ -n "$(git status --porcelain)" ]; then
    echo "Arbeitsbaum ist nicht sauber - erst einchecken, dann veroeffentlichen." >&2
    git status --short >&2
    exit 1
fi

echo "Baue $REGISTRY:$VERSION"
docker build --build-arg "VERSION=$VERSION" -t "$REGISTRY:v$VERSION" .

# Gegenprobe: meldet sich das Abbild wirklich so, wie es heisst?
GEMELDET=$(docker run --rm --entrypoint sh "$REGISTRY:v$VERSION" \
             -c "cat /app/app/_version.py" | grep -oP "(?<=version = ')[^']+")
if [ "$GEMELDET" != "$VERSION" ]; then
    echo "Abbild meldet '$GEMELDET', erwartet war '$VERSION'." >&2
    exit 1
fi
echo "Abbild meldet $GEMELDET"

if [ "$PUSH" = "1" ]; then
    for tag in stable latest beta; do
        docker tag "$REGISTRY:v$VERSION" "$REGISTRY:$tag"
    done
    for tag in "v$VERSION" stable latest beta; do
        echo "  veroeffentliche :$tag"
        docker push -q "$REGISTRY:$tag"
    done
    echo "Fertig. Produktion zieht $VERSION beim naechsten Update."
else
    echo "Nicht veroeffentlicht. Mit --push nachholen."
fi
