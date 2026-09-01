#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d /tmp/bpm-config-test.XXXXXX)

cleanup() {
    case "$test_dir" in
        /tmp/bpm-config-test.*) rm -rf -- "$test_dir" ;;
    esac
}
trap cleanup EXIT

mkdir -p "$test_dir/lib"
cp "$project_dir/lib/config.sh" "$test_dir/lib/config.sh"
# shellcheck source=/dev/null
source "$test_dir/lib/config.sh"

marker="$test_dir/executed"
unknown_marker="$test_dir/unknown-executed"
printf 'MBTC_CLI_PATH="/bin/echo"\nMBTC_DATADIR="$(touch %s)"\nUNKNOWN_KEY="$(touch %s)"\nMBTC_NETWORK="main"\n' \
    "$marker" "$unknown_marker" > "$MBTC_CACHE_FILE"
load_config

printf -v expected_datadir '$(touch %s)' "$marker"
[[ "$MBTC_DATADIR" == "$expected_datadir" ]]
[[ ! -e "$marker" && ! -e "$unknown_marker" ]]
[[ -z "${UNKNOWN_KEY+x}" ]]

helper="$test_dir/cli with spaces"
args_file="$test_dir/args"
printf '%s\n' '#!/bin/bash' 'printf "%s\0" "$@" > "$CONFIG_TEST_ARGS_FILE"' > "$helper"
chmod 700 "$helper"
export CONFIG_TEST_ARGS_FILE="$args_file"
MBTC_CLI_PATH="$helper"
MBTC_DATADIR="$test_dir/data dir;touch $marker"
MBTC_CONF="$test_dir/conf file \$(touch $marker)"
MBTC_NETWORK=signet
run_cli getblockchaininfo 'argument with spaces'

mapfile -d '' -t args < "$args_file"
[[ ${#args[@]} -eq 5 ]]
[[ "${args[0]}" == "-datadir=$MBTC_DATADIR" ]]
[[ "${args[1]}" == "-conf=$MBTC_CONF" ]]
[[ "${args[2]}" == "-signet" ]]
[[ "${args[3]}" == "getblockchaininfo" ]]
[[ "${args[4]}" == "argument with spaces" ]]
[[ ! -e "$marker" ]]

printf 'MBTC_CLI_PATH="/bin/true"\n' > "$MBTC_CACHE_FILE"
before_hash=$(sha256sum "$MBTC_CACHE_FILE")
! set_config MBTC_NOT_SUPPORTED value
! set_config GEO_DB_ENABLED $'true"\nMBTC_CLI_PATH="/tmp/injected-cli'
[[ "$(sha256sum "$MBTC_CACHE_FILE")" == "$before_hash" ]]

echo "Shell configuration tests passed"
