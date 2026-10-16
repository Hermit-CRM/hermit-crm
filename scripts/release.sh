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

# Build the download for the website: a versioned tarball and its checksum.
#
#   scripts/release.sh [--wheel FILE] [commit]      # default: HEAD
#
# Produces dist/hermitcrm-<version>.tar.gz, which unpacks to hermitcrm-<version>/.
# The version is in both names on purpose: someone who downloads twice needs to be
# able to tell the two folders apart, and a support question that starts "I unpacked
# hermitcrm-0.3.0" answers itself.
#
# git archive, not tar: it takes the tracked files at a commit, so nothing untracked
# (a .secrets.toml, a stray data folder, an editor backup) can be swept into a public
# download by accident. It also means uncommitted work is NOT in the tarball, which
# is why a dirty tree is called out below.
#
# Nothing is released until scripts/install-check.sh has installed it in a clean
# virtualenv and run it as a new user would. The download is the sdist half of
# that check: it is what `uv tool install .` builds from, so it is checked as
# built, not rebuilt. The wheel half is the --wheel FILE given (the release
# workflow passes the one it just put on PyPI), or else one built from the
# download. If the check fails, the tarball and checksum are removed again, so
# a broken download never sits in dist/ looking finished.
set -eu

die() { echo "release: $1" >&2; exit 1; }

wheel=""
while [ $# -gt 0 ]; do
    case "$1" in
        --wheel) [ $# -ge 2 ] || die "--wheel needs a file"; wheel=$2; shift 2 ;;
        --wheel=*) wheel=${1#--wheel=}; shift ;;
        -*) die "unknown option: $1 (usage: scripts/release.sh [--wheel FILE] [commit])" ;;
        *) break ;;
    esac
done
[ $# -le 1 ] || die "one commit at most (usage: scripts/release.sh [--wheel FILE] [commit])"

# Before the cd below, so a relative --wheel means what it did where you typed it.
if [ -n "$wheel" ]; then
    case "$wheel" in *.whl) ;; *) die "--wheel $wheel is not a .whl" ;; esac
    [ -f "$wheel" ] || die "no such wheel: $wheel"
    wheel="$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"
fi

cd "$(dirname "$0")/.."
commit="${1:-HEAD}"

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/hermitcrm/__init__.py)
[ -n "$version" ] || die "no __version__ in src/hermitcrm/__init__.py"

name="hermitcrm-$version"
out="dist/$name.tar.gz"

if [ -n "$(git status --porcelain)" ]; then
    echo "release: working tree is dirty; $commit is what gets packaged, not your edits" >&2
    git status --short >&2
    echo >&2
fi

[ -e "$out" ] && die "$out exists already. Bump __version__ or remove it first."

mkdir -p dist
# git archive creates $out before it looks at $commit; a typo must not leave an
# empty tarball that the exists-already check above then trips on.
git archive --format=tar.gz --prefix="$name/" -o "$out" "$commit" || {
    rm -f "$out"
    die "git archive failed for $commit"
}

if command -v shasum >/dev/null 2>&1; then
    ( cd dist && shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256" )
else
    ( cd dist && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256" )
fi

# --- the gate: does it install and run for a new user? -------------------------

work=$(mktemp -d "${TMPDIR:-/tmp}/hermitcrm-release.XXXXXX")
trap 'rm -rf "$work"' EXIT INT TERM

withdraw() {
    rm -f "$out" "$out.sha256"
    echo >&2
    die "$1; removed $out and its checksum, nothing is released"
}

if [ -z "$wheel" ]; then
    echo "Building a wheel from $out for the install check"
    python3 -m venv "$work/venv" || withdraw "could not create a virtualenv"
    "$work/venv/bin/pip" wheel -q --disable-pip-version-check --no-deps \
        -w "$work/wheel" "$out" >"$work/wheel.log" 2>&1 || {
        tail -40 "$work/wheel.log" >&2
        withdraw "no wheel builds from the download"
    }
    for f in "$work/wheel"/*.whl; do [ -f "$f" ] && wheel=$f; done
    [ -n "$wheel" ] || withdraw "building a wheel from the download produced none"
fi

scripts/install-check.sh "$wheel" "$out" || withdraw "the install check failed"

echo

echo "$out"
echo "$(cat "$out.sha256")"
echo
files=$(tar -tzf "$out" | grep -cv '/$')
echo "Built from $(git rev-parse --short "$commit"): $files files, $(du -h "$out" | cut -f1), unpacks to $name/."
echo "Put both files on the download page. To check one after downloading:"
echo "  shasum -a 256 -c $name.tar.gz.sha256   (macOS)"
echo "  sha256sum -c $name.tar.gz.sha256   (Linux)"
