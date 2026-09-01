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
printf 'BITCOIN_CLI="/bin/echo"\nBITCOIN_DATA_DIR="$(touch %s)"\nUNKNOWN_KEY="$(touch %s)"\nBITCOIN_NETWORK="main"\n' \
    "$marker" "$unknown_marker" > "$APP_CONFIG_FILE"
load_config

printf -v expected_datadir '$(touch %s)' "$marker"
[[ "$BITCOIN_DATA_DIR" == "$expected_datadir" ]]
[[ ! -e "$marker" && ! -e "$unknown_marker" ]]
[[ -z "${UNKNOWN_KEY+x}" ]]

helper="$test_dir/cli with spaces"
args_file="$test_dir/args"
printf '%s\n' '#!/bin/bash' 'printf "%s\0" "$@" > "$CONFIG_TEST_ARGS_FILE"' > "$helper"
chmod 700 "$helper"
export CONFIG_TEST_ARGS_FILE="$args_file"
BITCOIN_CLI="$helper"
BITCOIN_DATA_DIR="$test_dir/data dir;touch $marker"
BITCOIN_CONFIG_FILE="$test_dir/conf file \$(touch $marker)"
BITCOIN_NETWORK=signet
run_bitcoin_cli getblockchaininfo 'argument with spaces'

mapfile -d '' -t args < "$args_file"
[[ ${#args[@]} -eq 5 ]]
[[ "${args[0]}" == "-datadir=$BITCOIN_DATA_DIR" ]]
[[ "${args[1]}" == "-conf=$BITCOIN_CONFIG_FILE" ]]
[[ "${args[2]}" == "-signet" ]]
[[ "${args[3]}" == "getblockchaininfo" ]]
[[ "${args[4]}" == "argument with spaces" ]]
[[ ! -e "$marker" ]]

printf 'BITCOIN_CLI="/bin/true"\n' > "$APP_CONFIG_FILE"
before_hash=$(sha256sum "$APP_CONFIG_FILE")
! set_config BPM_NOT_SUPPORTED value
! set_config BPM_GEOIP_ENABLED $'true"\nBITCOIN_CLI="/tmp/injected-cli'
[[ "$(sha256sum "$APP_CONFIG_FILE")" == "$before_hash" ]]

echo "Shell configuration tests passed"
