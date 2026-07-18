#!/usr/bin/env bash
# Clone and build GROBID master (bare gradle build). Requires JDK 17 and git.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env

if ! command -v java >/dev/null; then
    echo "ERROR: java not found. Install JDK 17, e.g. via sdkman:" >&2
    echo '  curl -s "https://get.sdkman.io" | bash && sdk install java 17.0.10-tem' >&2
    exit 1
fi
java -version 2>&1 | head -1

mkdir -p "$(dirname "$GROBID_HOME_DIR")"
if [ -d "$GROBID_HOME_DIR/.git" ]; then
    echo "Updating existing clone at $GROBID_HOME_DIR"
    git -C "$GROBID_HOME_DIR" fetch origin && git -C "$GROBID_HOME_DIR" checkout master \
        && git -C "$GROBID_HOME_DIR" pull --ff-only
else
    git clone --branch master https://github.com/grobidOrg/grobid "$GROBID_HOME_DIR"
fi

cd "$GROBID_HOME_DIR"
./gradlew clean assemble -x test --no-daemon
echo "GROBID master built at $GROBID_HOME_DIR (rev $(git rev-parse --short HEAD))"
