#!/bin/bash
# Bitcoin Peer Map - shared configuration

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DATA_DIR="${BPM_DATA_DIR:-$PROJECT_ROOT/data}"
APP_CONFIG_FILE="$APP_DATA_DIR/config.conf"

BITCOIN_CLI=""
BITCOIN_DATA_DIR=""
BITCOIN_CONFIG_FILE=""
BITCOIN_NETWORK="main"
BITCOIN_RPC_HOST="127.0.0.1"
BITCOIN_RPC_PORT="8332"
BITCOIN_RPC_USER=""
BITCOIN_RPC_PASSWORD=""
BITCOIN_RPC_COOKIE_FILE=""
BITCOIN_CLI_VERSION=""
BPM_LISTEN_PORT="58333"
BPM_LISTEN_ADDRESS="0.0.0.0"
BPM_GEOIP_ENABLED="true"
BPM_GEOIP_AUTO_UPDATE="true"
config_ready=0

is_config_key() {
    case "$1" in
        BITCOIN_CLI|BITCOIN_DATA_DIR|BITCOIN_CONFIG_FILE|BITCOIN_NETWORK|BITCOIN_RPC_HOST|BITCOIN_RPC_PORT|BITCOIN_RPC_USER|BITCOIN_RPC_COOKIE_FILE|BPM_LISTEN_PORT|BPM_LISTEN_ADDRESS|BPM_GEOIP_ENABLED|BPM_GEOIP_AUTO_UPDATE) return 0 ;;
        *) return 1 ;;
    esac
}

is_single_line_config_value() {
    [[ "$1" != *$'\n'* && "$1" != *$'\r'* ]]
}

read_config_value() {
    local key="$1"
    [[ -f "$APP_CONFIG_FILE" ]] || return 1

    awk -F= -v key="$key" '
        $1 == key {
            value = substr($0, index($0, "=") + 1)
            gsub(/^[[:space:]]*[\047\042]|[\047\042][[:space:]]*$/, "", value)
            print value
            found = 1
            exit
        }
        END { if (!found) exit 1 }
    ' "$APP_CONFIG_FILE"
}

load_config() {
    config_ready=0
    [[ -f "$APP_CONFIG_FILE" ]] || return 1

    local key value
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        is_config_key "$key" || continue

        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
            value="${value:1:${#value}-2}"
        fi
        printf -v "$key" '%s' "$value"
    done < "$APP_CONFIG_FILE"

    [[ -n "$BITCOIN_CLI" ]] || return 1
    config_ready=1
}

save_config() {
    local value
    for value in \
        "$BITCOIN_CLI" "$BITCOIN_DATA_DIR" "$BITCOIN_CONFIG_FILE" "$BITCOIN_NETWORK" \
        "$BITCOIN_RPC_HOST" "$BITCOIN_RPC_PORT" "$BITCOIN_RPC_USER" "$BITCOIN_RPC_COOKIE_FILE" \
        "$BPM_LISTEN_PORT" "$BPM_LISTEN_ADDRESS" "$BPM_GEOIP_ENABLED" "$BPM_GEOIP_AUTO_UPDATE"; do
        is_single_line_config_value "$value" || return 1
    done

    mkdir -p "$APP_DATA_DIR"
    local temp_config
    temp_config=$(mktemp "$APP_DATA_DIR/.config.conf.XXXXXX")

    cat > "$temp_config" <<EOF
# Bitcoin Peer Map configuration
# Generated: $(date)

BITCOIN_CLI="$BITCOIN_CLI"
BITCOIN_DATA_DIR="$BITCOIN_DATA_DIR"
BITCOIN_CONFIG_FILE="$BITCOIN_CONFIG_FILE"
BITCOIN_NETWORK="$BITCOIN_NETWORK"
BITCOIN_RPC_HOST="$BITCOIN_RPC_HOST"
BITCOIN_RPC_PORT="$BITCOIN_RPC_PORT"
BITCOIN_RPC_USER="$BITCOIN_RPC_USER"
BITCOIN_RPC_COOKIE_FILE="$BITCOIN_RPC_COOKIE_FILE"
BPM_LISTEN_PORT="${BPM_LISTEN_PORT:-58333}"
BPM_LISTEN_ADDRESS="${BPM_LISTEN_ADDRESS:-0.0.0.0}"
BPM_GEOIP_ENABLED="${BPM_GEOIP_ENABLED:-true}"
BPM_GEOIP_AUTO_UPDATE="${BPM_GEOIP_AUTO_UPDATE:-true}"
EOF

    chmod 600 "$temp_config"
    mv "$temp_config" "$APP_CONFIG_FILE"
    config_ready=1
}

get_config() {
    local key="$1"
    local default="${2:-}"
    local value

    value=$(read_config_value "$key" 2>/dev/null || true)
    printf '%s\n' "${value:-$default}"
}

set_config() {
    local key="$1"
    local value="$2"

    is_config_key "$key" || return 1
    is_single_line_config_value "$value" || return 1

    mkdir -p "$APP_DATA_DIR"
    local temp_config
    temp_config=$(mktemp "$APP_DATA_DIR/.config.conf.XXXXXX")
    if [[ -f "$APP_CONFIG_FILE" ]]; then
        awk -F= -v key="$key" '$1 != key' "$APP_CONFIG_FILE" > "$temp_config"
    fi
    printf '%s="%s"\n' "$key" "$value" >> "$temp_config"
    chmod 600 "$temp_config"
    mv "$temp_config" "$APP_CONFIG_FILE"
}

has_config() {
    local key="$1"
    [[ -f "$APP_CONFIG_FILE" ]] && grep -q "^${key}=" "$APP_CONFIG_FILE" 2>/dev/null
}

config_exists() {
    load_config &>/dev/null
}

clear_config() {
    rm -f "$APP_CONFIG_FILE"
    BITCOIN_CLI=""
    BITCOIN_DATA_DIR=""
    BITCOIN_CONFIG_FILE=""
    BITCOIN_NETWORK="main"
    BITCOIN_RPC_HOST="127.0.0.1"
    BITCOIN_RPC_PORT="8332"
    BITCOIN_RPC_USER=""
    BITCOIN_RPC_PASSWORD=""
    BITCOIN_RPC_COOKIE_FILE=""
    BITCOIN_CLI_VERSION=""
    BPM_LISTEN_PORT="58333"
    BPM_LISTEN_ADDRESS="0.0.0.0"
    BPM_GEOIP_ENABLED="true"
    BPM_GEOIP_AUTO_UPDATE="true"
    config_ready=0
}

build_bitcoin_cli_command() {
    local -n command_ref=$1
    command_ref=("${BITCOIN_CLI:-bitcoin-cli}")
    [[ -n "$BITCOIN_DATA_DIR" ]] && command_ref+=("-datadir=$BITCOIN_DATA_DIR")
    [[ -n "$BITCOIN_CONFIG_FILE" ]] && command_ref+=("-conf=$BITCOIN_CONFIG_FILE")

    case "$BITCOIN_NETWORK" in
        test) command_ref+=("-testnet") ;;
        signet) command_ref+=("-signet") ;;
        regtest) command_ref+=("-regtest") ;;
    esac
}

get_bitcoin_cli_command() {
    local -a command
    build_bitcoin_cli_command command
    printf '%q ' "${command[@]}"
    printf '\n'
}

run_bitcoin_cli() {
    local -a command
    build_bitcoin_cli_command command
    "${command[@]}" "$@"
}

test_rpc() {
    run_bitcoin_cli getblockchaininfo &>/dev/null
}

mkdir -p "$APP_DATA_DIR"
load_config 2>/dev/null || true
