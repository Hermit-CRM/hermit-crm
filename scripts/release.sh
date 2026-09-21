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
#   scripts/release.sh [commit]      # default: HEAD
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
set -eu

cd "$(dirname "$0")/.."
commit="${1:-HEAD}"

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/hermitcrm/__init__.py)
[ -n "$version" ] || { echo "release: no __version__ in src/hermitcrm/__init__.py" >&2; exit 1; }

name="hermitcrm-$version"
out="dist/$name.tar.gz"

if [ -n "$(git status --porcelain)" ]; then
    echo "release: working tree is dirty; $commit is what gets packaged, not your edits" >&2
    git status --short >&2
    echo >&2
fi

if [ -e "$out" ]; then
    echo "release: $out exists already. Bump __version__ or remove it first." >&2
    exit 1
fi

mkdir -p dist
git archive --format=tar.gz --prefix="$name/" -o "$out" "$commit"

if command -v shasum >/dev/null 2>&1; then
    ( cd dist && shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256" )
else
    ( cd dist && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256" )
fi

echo "$out"
echo "$(cat "$out.sha256")"
echo
files=$(tar -tzf "$out" | grep -cv '/$')
echo "Built from $(git rev-parse --short "$commit"): $files files, $(du -h "$out" | cut -f1), unpacks to $name/."
echo "Put both files on the download page. To check one after downloading:"
echo "  shasum -a 256 -c $name.tar.gz.sha256   (macOS)"
echo "  sha256sum -c $name.tar.gz.sha256   (Linux)"
