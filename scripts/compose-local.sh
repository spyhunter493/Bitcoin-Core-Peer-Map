#!/usr/bin/env sh
set -eu

if [ "${BPM_BUILD_REVISION:-}" = "" ]; then
    if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if git diff --quiet --ignore-submodules -- && git diff --cached --quiet --ignore-submodules --; then
            BPM_BUILD_REVISION="$(git rev-parse HEAD)"
        else
            BPM_BUILD_REVISION="unknown"
        fi
    else
        BPM_BUILD_REVISION="unknown"
    fi
    export BPM_BUILD_REVISION
fi

exec docker compose "$@"
