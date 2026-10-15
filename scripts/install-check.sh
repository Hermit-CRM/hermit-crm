#!/bin/sh
# Copyright 2026 Gijs Bos
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Does `pip install hermitcrm` work for a new user?
#
#   scripts/install-check.sh                            # build sdist + wheel, then check them
#   scripts/install-check.sh dist/*.whl dist/*.tar.gz   # check artifacts already built
#
# The only honest test is a clean-room one: a brand-new virtualenv with nothing
# carried over from your working environment, then the first commands a new user
# runs. CI's `uv sync --locked` proves the pinned dependencies resolve against
# each other; this proves what a stranger actually gets from `pip install
# hermitcrm` once upstream has moved on. It is the step that catches a wheel
# with no entry point, an sdist missing its templates, and a dependency pin
# nothing has resolved yet.
#
# Per artifact -- the wheel and the sdist, each in its own venv -- it checks:
#   install, `hermitcrm --version` names the version being released,
#   `init` a new data folder, `check` clean, `rebuild`, `digest`, `doctor`
#   with no failing line, and the web app answering on a local port.
#
# It cleans up after itself and exits non-zero at the first failure, so it can
# gate a release. Needs python3 (3.11+), git and curl on PATH; `build` is installed
# into a throwaway venv, so nothing has to be set up first.
set -eu

cd "$(dirname "$0")/.."

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/hermitcrm/__init__.py)
[ -n "$version" ] || { echo "install-check: no __version__ in src/hermitcrm/__init__.py" >&2; exit 1; }

work=${TMPDIR:-/tmp}/hermitcrm-install-check-$$
rm -rf "$work"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT INT TERM

step() { printf '\n== %s\n' "$1"; }
die() { echo "install-check: $1" >&2; exit 1; }
abspath() {
    d=$(cd "$(dirname "$1")" && pwd)
    printf '%s/%s\n' "$d" "$(basename "$1")"
}

# --- which artifacts ----------------------------------------------------------

wheel=""
sdist=""
for f in "$@"; do
    [ -f "$f" ] || die "no such file: $f"
    case "$f" in
        *.whl) wheel=$(abspath "$f") ;;
        *.tar.gz) sdist=$(abspath "$f") ;;
        *) die "not an artifact: $f (expected a .whl or a .tar.gz)" ;;
    esac
done

# Both or neither: checking one artifact and quietly rebuilding the other would
# pass for something that was never going to be released.
if [ -n "$wheel" ] && [ -z "$sdist" ]; then die "a wheel but no sdist given; pass both or neither"; fi
if [ -z "$wheel" ] && [ -n "$sdist" ]; then die "an sdist but no wheel given; pass both or neither"; fi

built=""
if [ -z "$wheel" ]; then
    built=1
    step "Building sdist and wheel"
    buildenv="$work/buildenv"
    python3 -m venv "$buildenv"
    "$buildenv/bin/pip" install -q --disable-pip-version-check build
    "$buildenv/bin/python" -m build --outdir "$work/dist" >"$work/build.log" 2>&1 || {
        tail -40 "$work/build.log" >&2
        die "the build failed"
    }
    for f in "$work/dist"/*.whl; do [ -f "$f" ] && wheel=$f; done
    for f in "$work/dist"/*.tar.gz; do [ -f "$f" ] && sdist=$f; done
    [ -n "$wheel" ] && [ -n "$sdist" ] || die "the build produced no wheel or no sdist"
fi

step "Checking hermitcrm $version"

# --- one clean-room install, end to end ---------------------------------------

# check <label> <artifact>
check() {
    label=$1
    artifact=$2
    step "Clean-room install: $label"

    venv="$work/venv-$label"
    python3 -m venv "$venv" || die "could not create a virtualenv"
    "$venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
    "$venv/bin/pip" install "$artifact" >"$work/pip-$label.log" 2>&1 || {
        tail -40 "$work/pip-$label.log" >&2
        die "pip install failed for the $label"
    }

    hcrm="$venv/bin/hermitcrm"
    [ -x "$hcrm" ] || die "no hermitcrm command after installing the $label"

    got=$("$hcrm" --version 2>&1) || die "hermitcrm --version failed for the $label"
    echo "  version: $got"
    [ "$got" = "hermitcrm $version" ] ||
        die "the $label reports '$got', expected 'hermitcrm $version'"

    # A new user's folder: demo data, no questions, no network.
    data="$work/data-$label"
    HERMITCRM_NO_UPDATE_CHECK=1 "$hcrm" init --demo --no-setup "$data" \
        >"$work/init-$label.log" 2>&1 || {
        cat "$work/init-$label.log" >&2
        die "init failed for the $label"
    }
    echo "  init: $(tail -1 "$work/init-$label.log")"

    # Local, not global: this script must not touch the machine's git config.
    git -C "$data" config user.name "hermitcrm install check"
    git -C "$data" config user.email "install-check@example.com"

    out=$( cd "$data" && HERMITCRM_NO_UPDATE_CHECK=1 "$hcrm" check ) ||
        die "check reported problems for the $label"
    echo "  check: $(printf '%s' "$out" | tail -1)"

    ( cd "$data" && HERMITCRM_NO_UPDATE_CHECK=1 "$hcrm" rebuild >/dev/null ) ||
        die "rebuild failed for the $label"
    ( cd "$data" && HERMITCRM_NO_UPDATE_CHECK=1 "$hcrm" digest --days 3650 >/dev/null ) ||
        die "digest failed for the $label"

    # Warns are a new user's normal state (no remote, no backup yet); only a
    # failing line means the install is broken.
    doc=$( cd "$data" && HERMITCRM_NO_UPDATE_CHECK=1 "$hcrm" doctor ) || true
    if printf '%s\n' "$doc" | grep -q '^fail'; then
        printf '%s\n' "$doc" | grep '^fail' >&2
        die "doctor found a failing check for the $label"
    fi
    echo "  doctor: $(printf '%s\n' "$doc" | grep -c '^ok') ok," \
         "$(printf '%s\n' "$doc" | grep -c '^warn') warn, 0 fail"

    # The web app is the other half of the install: an sdist that lost its
    # templates still installs and still passes check.
    port=$("$venv/bin/python" -c 'import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()')
    ( cd "$data" && HERMITCRM_NO_UPDATE_CHECK=1 exec "$hcrm" serve --port "$port" \
        >"$work/serve-$label.log" 2>&1 ) &
    serve_pid=$!
    served=""
    i=0
    while [ "$i" -lt 40 ]; do
        if curl -fsS -o /dev/null "http://127.0.0.1:$port/pipeline" 2>/dev/null; then
            served=1
            break
        fi
        kill -0 "$serve_pid" 2>/dev/null || break
        i=$((i + 1))
        sleep 0.5
    done
    kill "$serve_pid" 2>/dev/null || true
    wait "$serve_pid" 2>/dev/null || true
    [ -n "$served" ] || {
        cat "$work/serve-$label.log" >&2
        die "the web app did not answer for the $label"
    }
    echo "  serve: HTTP 200 on http://127.0.0.1:$port/pipeline"
}

check wheel "$wheel"
check sdist "$sdist"

step "OK: hermitcrm $version installs and runs for a new user"

# Artifacts built here live in $work and are gone once this exits.
if [ -z "$built" ]; then
    echo "  wheel: $wheel"
    echo "  sdist: $sdist"
fi
