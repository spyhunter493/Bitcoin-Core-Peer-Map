#!/bin/bash
# MBTC-DASH - Shared Configuration
# Handles loading/saving config that all scripts share

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION PATHS
# ═══════════════════════════════════════════════════════════════════════════════

# Use local data folder within the project
MBTC_BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MBTC_CONFIG_DIR="$MBTC_BASE_DIR/data"
export MBTC_DATA_DIR="$MBTC_BASE_DIR/data"
export MBTC_CACHE_FILE="$MBTC_CONFIG_DIR/config.conf"

# ═══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT VARIABLES (MBTC_ prefix)
# ═══════════════════════════════════════════════════════════════════════════════

# These are set when config is loaded
export MBTC_CLI_PATH=""
export MBTC_DATADIR=""
export MBTC_CONF=""
export MBTC_NETWORK="main"
export MBTC_RPC_HOST="127.0.0.1"
export MBTC_RPC_PORT="8332"
export MBTC_RPC_USER=""
export MBTC_RPC_PASS=""
export MBTC_COOKIE_PATH=""
export MBTC_VERSION=""
export MBTC_WEB_PORT="58333"
export MBTC_WEB_BIND="0.0.0.0"
export MBTC_CONFIGURED=0

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG FILE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Load configuration from cache file
# Returns: 0 if loaded successfully, 1 if no config exists
load_config() {
    [[ ! -f "$MBTC_CACHE_FILE" ]] && return 1

    local key value
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" == \#* ]] && continue
        case "$key" in
            MBTC_CLI_PATH|MBTC_DATADIR|MBTC_CONF|MBTC_NETWORK|MBTC_RPC_HOST|MBTC_RPC_PORT|MBTC_RPC_USER|MBTC_COOKIE_PATH|MBTC_WEB_PORT|MBTC_WEB_BIND|MBTC_CONFIGURED|GEO_DB_ENABLED|GEO_DB_AUTO_UPDATE) ;;
            *) continue ;;
        esac

        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
            value="${value:1:${#value}-2}"
        fi
        printf -v "$key" '%s' "$value"
        export "$key"
    done < "$MBTC_CACHE_FILE"

    [[ -z "$MBTC_CLI_PATH" ]] && return 1
    MBTC_CONFIGURED=1
    return 0
}

# Save current configuration to cache file
# Preserves any extra keys (GEO_DB_*, etc.) that were added via set_config
save_config() {
    mkdir -p "$MBTC_CONFIG_DIR"

    # Collect extra keys that aren't part of the core config
    local extra_lines=""
    if [[ -f "$MBTC_CACHE_FILE" ]]; then
        extra_lines=$(grep -v '^#' "$MBTC_CACHE_FILE" | grep -v '^$' | grep -v '^MBTC_' 2>/dev/null || true)
    fi

    cat > "$MBTC_CACHE_FILE" << EOF
# MBTC-DASH Configuration
# Generated: $(date)

MBTC_CLI_PATH="$MBTC_CLI_PATH"
MBTC_DATADIR="$MBTC_DATADIR"
MBTC_CONF="$MBTC_CONF"
MBTC_NETWORK="$MBTC_NETWORK"
MBTC_RPC_HOST="$MBTC_RPC_HOST"
MBTC_RPC_PORT="$MBTC_RPC_PORT"
MBTC_RPC_USER="$MBTC_RPC_USER"
MBTC_COOKIE_PATH="$MBTC_COOKIE_PATH"
MBTC_WEB_PORT="${MBTC_WEB_PORT:-58333}"
MBTC_WEB_BIND="${MBTC_WEB_BIND:-0.0.0.0}"
MBTC_CONFIGURED=1
EOF

    # Re-append extra keys
    if [[ -n "$extra_lines" ]]; then
        echo "" >> "$MBTC_CACHE_FILE"
        echo "$extra_lines" >> "$MBTC_CACHE_FILE"
    fi

    chmod 600 "$MBTC_CACHE_FILE"
}

# Get a config value with optional default
# Usage: value=$(get_config "KEY" "default")
get_config() {
    local key="$1"
    local default="${2:-}"
    local value=""

    if [[ -f "$MBTC_CACHE_FILE" ]]; then
        value=$(grep "^${key}=" "$MBTC_CACHE_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"')
    fi

    echo "${value:-$default}"
}

# Set a config value
# Usage: set_config "KEY" "value"
set_config() {
    local key="$1"
    local value="$2"

    [[ "$key" =~ ^(MBTC_[A-Z0-9_]+|GEO_DB_(ENABLED|AUTO_UPDATE))$ ]] || return 1

    mkdir -p "$MBTC_CONFIG_DIR"

    # Create file if it doesn't exist
    [[ ! -f "$MBTC_CACHE_FILE" ]] && touch "$MBTC_CACHE_FILE" && chmod 600 "$MBTC_CACHE_FILE"

    # Remove existing key if present
    if grep -q "^${key}=" "$MBTC_CACHE_FILE" 2>/dev/null; then
        sed -i "/^${key}=/d" "$MBTC_CACHE_FILE"
    fi

    # Append new value
    echo "${key}=\"${value}\"" >> "$MBTC_CACHE_FILE"
}

# Check if a key exists in config (regardless of value)
# Usage: if has_config "KEY"; then ...
has_config() {
    local key="$1"
    [[ -f "$MBTC_CACHE_FILE" ]] && grep -q "^${key}=" "$MBTC_CACHE_FILE" 2>/dev/null
}

# Check if config exists and is valid
config_exists() {
    [[ -f "$MBTC_CACHE_FILE" ]] && load_config &>/dev/null
}

# Clear saved configuration
clear_config() {
    rm -f "$MBTC_CACHE_FILE"
    MBTC_CLI_PATH=""
    MBTC_DATADIR=""
    MBTC_CONF=""
    MBTC_NETWORK="main"
    MBTC_RPC_HOST="127.0.0.1"
    MBTC_RPC_PORT="8332"
    MBTC_RPC_USER=""
    MBTC_RPC_PASS=""
    MBTC_COOKIE_PATH=""
    MBTC_VERSION=""
    MBTC_WEB_PORT="58333"
    MBTC_WEB_BIND="0.0.0.0"
    MBTC_CONFIGURED=0
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLI COMMAND BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

# Build bitcoin-cli command with all necessary flags
build_cli_command() {
    MBTC_CLI_CMD=("${MBTC_CLI_PATH:-bitcoin-cli}")
    [[ -n "$MBTC_DATADIR" ]] && MBTC_CLI_CMD+=("-datadir=$MBTC_DATADIR")
    [[ -n "$MBTC_CONF" ]] && MBTC_CLI_CMD+=("-conf=$MBTC_CONF")

    case "$MBTC_NETWORK" in
        test) MBTC_CLI_CMD+=("-testnet") ;;
        signet) MBTC_CLI_CMD+=("-signet") ;;
        regtest) MBTC_CLI_CMD+=("-regtest") ;;
    esac
}

get_cli_command() {
    build_cli_command
    printf '%q ' "${MBTC_CLI_CMD[@]}"
    printf '\n'
}

run_cli() {
    build_cli_command
    "${MBTC_CLI_CMD[@]}" "$@"
}

# Test RPC connection
test_rpc() {
    run_cli getblockchaininfo &>/dev/null
}

# ═══════════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

# Ensure directories exist
init_dirs() {
    mkdir -p "$MBTC_CONFIG_DIR"
    mkdir -p "$MBTC_DATA_DIR"
}

# Auto-load config on source (but don't fail if not found)
init_dirs
load_config 2>/dev/null || true
