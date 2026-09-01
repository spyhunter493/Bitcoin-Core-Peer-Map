#!/bin/bash
# Bitcoin Peer Map - Bitcoin Core Detection Script
# Detects Bitcoin Core installation, datadir, conf, and auth settings

# Don't use set -e - we handle errors ourselves

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source libraries
source "$PROJECT_ROOT/lib/ui.sh"
source "$PROJECT_ROOT/lib/config.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Common datadir locations
DATADIR_CANDIDATES=(
    "$HOME/.bitcoin"
    "/var/lib/bitcoind"
    "/var/lib/bitcoin"
    "/srv/bitcoin"
    "/data/bitcoin"
    "/opt/bitcoin/data"
    "/home/bitcoin/.bitcoin"
)

# Fallback binary search paths
BINARY_SEARCH_PATHS=(
    "/usr/bin"
    "/usr/local/bin"
    "/opt/bitcoin/bin"
    "/snap/bin"
    "$HOME/bin"
    "$HOME/.local/bin"
)

# Common conf file locations
CONF_CANDIDATES=(
    "$HOME/.bitcoin/bitcoin.conf"
    "/etc/bitcoin/bitcoin.conf"
    "/etc/bitcoind/bitcoin.conf"
    "/srv/bitcoin/bitcoin.conf"
    "/var/lib/bitcoind/bitcoin.conf"
)

# Track if bitcoind is running
node_running=0

# ═══════════════════════════════════════════════════════════════════════════════
# CTRL+C HANDLING
# ═══════════════════════════════════════════════════════════════════════════════

CTRL_C_COUNT=0
CTRL_C_TIME=0

handle_ctrl_c() {
    local now
    now=$(date +%s)

    if (( now - CTRL_C_TIME > 2 )); then
        CTRL_C_COUNT=0
    fi

    CTRL_C_TIME=$now
    ((CTRL_C_COUNT++))

    if [[ $CTRL_C_COUNT -eq 1 ]]; then
        echo ""
        msg_warn "Press Ctrl+C again to force quit (or wait for current operation to finish)"
    else
        echo ""
        msg_info "Force quitting..."
        cursor_show
        exit 130
    fi
}

trap handle_ctrl_c SIGINT

# ═══════════════════════════════════════════════════════════════════════════════
# CACHE DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

display_cached_config() {
    echo ""
    echo -e "${T_SECONDARY}${BOLD}Cached Configuration:${RST}"
    echo ""
    print_kv "Bitcoin CLI" "${BITCOIN_CLI:-not set}" 18
    print_kv "Data Directory" "${BITCOIN_DATA_DIR:-not set}" 18
    print_kv "Config File" "${BITCOIN_CONFIG_FILE:-not set}" 18
    print_kv "Network" "${BITCOIN_NETWORK:-main}" 18
    print_kv "RPC Host:Port" "${BITCOIN_RPC_HOST:-127.0.0.1}:${BITCOIN_RPC_PORT:-8332}" 18
    if [[ -n "$BITCOIN_RPC_COOKIE_FILE" ]]; then
        print_kv "Auth" "Cookie ($BITCOIN_RPC_COOKIE_FILE)" 18
    elif [[ -n "$BITCOIN_RPC_USER" ]]; then
        print_kv "Auth" "User/Pass ($BITCOIN_RPC_USER)" 18
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# PROCESS DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

detect_running_process() {
    local pinfo
    pinfo=$(pgrep -a bitcoind 2>/dev/null | head -1) || return 1
    [[ -z "$pinfo" ]] && return 1

    node_running=1

    local args
    args=$(echo "$pinfo" | cut -d' ' -f3-)

    # Parse arguments from running process
    [[ "$args" =~ -datadir=([^[:space:]]+) ]] && BITCOIN_DATA_DIR="${BASH_REMATCH[1]}"
    [[ "$args" =~ -conf=([^[:space:]]+) ]] && BITCOIN_CONFIG_FILE="${BASH_REMATCH[1]}"

    if [[ "$args" =~ -testnet ]]; then
        BITCOIN_NETWORK="test"
        BITCOIN_RPC_PORT="18332"
    elif [[ "$args" =~ -signet ]]; then
        BITCOIN_NETWORK="signet"
        BITCOIN_RPC_PORT="38332"
    elif [[ "$args" =~ -regtest ]]; then
        BITCOIN_NETWORK="regtest"
        BITCOIN_RPC_PORT="18443"
    fi

    [[ "$args" =~ -rpcport=([0-9]+) ]] && BITCOIN_RPC_PORT="${BASH_REMATCH[1]}"
    [[ "$args" =~ -rpcuser=([^[:space:]]+) ]] && BITCOIN_RPC_USER="${BASH_REMATCH[1]}"
    [[ "$args" =~ -rpcpassword=([^[:space:]]+) ]] && BITCOIN_RPC_PASSWORD="${BASH_REMATCH[1]}"
    [[ "$args" =~ -rpccookiefile=([^[:space:]]+) ]] && BITCOIN_RPC_COOKIE_FILE="${BASH_REMATCH[1]}"

    return 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEMD DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

detect_systemd_service() {
    command -v systemctl &>/dev/null || return 1

    local services
    services=$(systemctl list-units --type=service --all 2>/dev/null | grep -iE 'bitcoin' | awk '{print $1}')
    [[ -z "$services" ]] && return 1

    for service in $services; do
        systemctl is-active --quiet "$service" 2>/dev/null || continue

        local exec_start
        exec_start=$(systemctl show "$service" --property=ExecStart 2>/dev/null)

        [[ "$exec_start" =~ -datadir=([^[:space:]\;]+) ]] && BITCOIN_DATA_DIR="${BASH_REMATCH[1]}"
        [[ "$exec_start" =~ -conf=([^[:space:]\;]+) ]] && BITCOIN_CONFIG_FILE="${BASH_REMATCH[1]}"

        [[ -n "$BITCOIN_DATA_DIR" || -n "$BITCOIN_CONFIG_FILE" ]] && return 0
    done

    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# BITCOIN-CLI DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

detect_bitcoin_cli() {
    # Just try running it
    local result
    result=$(bitcoin-cli --version 2>&1)
    local exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        BITCOIN_CLI=$(command -v bitcoin-cli)
        BITCOIN_CLI_VERSION=$(echo "$result" | head -1 | grep -oP 'v[\d.]+' || echo "unknown")
        return 0
    fi

    # Command not found - search for it
    if [[ "$result" == *"command not found"* ]] || [[ "$result" == *"not found"* ]]; then
        for dir in "${BINARY_SEARCH_PATHS[@]}"; do
            if [[ -x "$dir/bitcoin-cli" ]]; then
                local test_result
                test_result=$("$dir/bitcoin-cli" --version 2>&1)
                if [[ $? -eq 0 ]]; then
                    BITCOIN_CLI="$dir/bitcoin-cli"
                    BITCOIN_CLI_VERSION=$(echo "$test_result" | head -1 | grep -oP 'v[\d.]+' || echo "unknown")
                    return 0
                fi
            fi
        done
        return 1
    fi

    # Some other error but cli exists
    BITCOIN_CLI=$(command -v bitcoin-cli 2>/dev/null)
    [[ -n "$BITCOIN_CLI" ]] && return 0

    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG FILE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

validate_conf_file() {
    local conf="$1"
    [[ -f "$conf" ]] && return 0
    return 1
}

validate_datadir() {
    local dir="$1"
    [[ ! -d "$dir" ]] && return 1

    if [[ -d "$dir/blocks" ]] || [[ -f "$dir/bitcoin.conf" ]] || [[ -f "$dir/.cookie" ]]; then
        return 0
    fi

    for subdir in testnet3 signet regtest; do
        [[ -d "$dir/$subdir/blocks" ]] && return 0
    done

    return 1
}

find_conf_file() {
    [[ -n "$BITCOIN_CONFIG_FILE" ]] && validate_conf_file "$BITCOIN_CONFIG_FILE" && return 0

    if [[ -n "$BITCOIN_DATA_DIR" && -f "$BITCOIN_DATA_DIR/bitcoin.conf" ]]; then
        BITCOIN_CONFIG_FILE="$BITCOIN_DATA_DIR/bitcoin.conf"
        return 0
    fi

    for conf in "${CONF_CANDIDATES[@]}"; do
        if validate_conf_file "$conf"; then
            BITCOIN_CONFIG_FILE="$conf"
            if [[ -z "$BITCOIN_DATA_DIR" ]]; then
                local dir
                dir=$(dirname "$conf")
                if validate_datadir "$dir"; then
                    BITCOIN_DATA_DIR="$dir"
                fi
            fi
            return 0
        fi
    done

    return 1
}

parse_conf_file() {
    local conf="$1"
    [[ ! -f "$conf" ]] && return 1

    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue

        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)

        case "$key" in
            datadir)     [[ -z "$BITCOIN_DATA_DIR" ]] && BITCOIN_DATA_DIR="$value" ;;
            testnet)     [[ "$value" == "1" ]] && BITCOIN_NETWORK="test" && BITCOIN_RPC_PORT="18332" ;;
            signet)      [[ "$value" == "1" ]] && BITCOIN_NETWORK="signet" && BITCOIN_RPC_PORT="38332" ;;
            regtest)     [[ "$value" == "1" ]] && BITCOIN_NETWORK="regtest" && BITCOIN_RPC_PORT="18443" ;;
            rpcuser)     BITCOIN_RPC_USER="$value" ;;
            rpcpassword) BITCOIN_RPC_PASSWORD="$value" ;;
            rpcport)     BITCOIN_RPC_PORT="$value" ;;
            rpcbind)     [[ "$BITCOIN_RPC_HOST" == "127.0.0.1" ]] && BITCOIN_RPC_HOST="$value" ;;
            rpccookiefile) BITCOIN_RPC_COOKIE_FILE="$value" ;;
        esac
    done < "$conf"
    return 0
}

search_conf_file() {
    echo ""
    msg_warn "This may take a while depending on your system..."
    echo ""

    start_spinner "Searching entire system for bitcoin.conf"
    local found
    found=$(find / -name "bitcoin.conf" -type f 2>/dev/null | head -10)
    stop_spinner 0 "Search complete"

    if [[ -z "$found" ]]; then
        msg_err "No bitcoin.conf found on system"
        return 1
    fi

    echo ""
    echo -e "${T_SECONDARY}Found these config files:${RST}"
    echo ""

    local i=1
    local -a found_array
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        found_array+=("$file")
        echo -e "  ${T_INFO}${i})${RST} $file"
        ((i++))
    done <<< "$found"

    echo -e "  ${T_WARN}b)${RST} Go back"
    echo ""

    local choice
    echo -en "${T_DIM}Select config file [1-$((i-1))]:${RST} "
    read -r choice

    if [[ "$choice" == "b" || "$choice" == "B" ]]; then
        return 2
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice < i )); then
        BITCOIN_CONFIG_FILE="${found_array[$((choice-1))]}"
        msg_ok "Selected: $BITCOIN_CONFIG_FILE"
        return 0
    fi

    msg_err "Invalid selection"
    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# DATADIR DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

find_datadir() {
    [[ -n "$BITCOIN_DATA_DIR" ]] && validate_datadir "$BITCOIN_DATA_DIR" && return 0

    if [[ -n "$BITCOIN_CONFIG_FILE" ]]; then
        local conf_dir
        conf_dir=$(dirname "$BITCOIN_CONFIG_FILE")
        if validate_datadir "$conf_dir"; then
            BITCOIN_DATA_DIR="$conf_dir"
            return 0
        fi
    fi

    if validate_datadir "$HOME/.bitcoin"; then
        BITCOIN_DATA_DIR="$HOME/.bitcoin"
        return 0
    fi

    for dir in "${DATADIR_CANDIDATES[@]}"; do
        if validate_datadir "$dir"; then
            BITCOIN_DATA_DIR="$dir"
            return 0
        fi
    done

    for mount in /mnt/* /media/*/* /data/*; do
        [[ -d "$mount" ]] || continue
        for subdir in bitcoin .bitcoin bitcoind; do
            if validate_datadir "$mount/$subdir"; then
                BITCOIN_DATA_DIR="$mount/$subdir"
                return 0
            fi
        done
    done 2>/dev/null

    return 1
}

search_datadir() {
    echo ""
    msg_warn "Searching for blocks/blk*.dat files - this may take a LONG time..."
    echo ""

    start_spinner "Searching entire system for Bitcoin data"
    local found
    found=$(find / -name "blk00000.dat" -type f 2>/dev/null | head -5)
    stop_spinner 0 "Search complete"

    if [[ -z "$found" ]]; then
        msg_err "No Bitcoin blockchain data found on system"
        return 1
    fi

    echo ""
    echo -e "${T_SECONDARY}Found blockchain data in:${RST}"
    echo ""

    local i=1
    local -a found_array
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        local datadir
        datadir=$(dirname "$(dirname "$file")")
        found_array+=("$datadir")
        echo -e "  ${T_INFO}${i})${RST} $datadir"
        ((i++))
    done <<< "$found"

    echo -e "  ${T_WARN}b)${RST} Go back"
    echo ""

    local choice
    echo -en "${T_DIM}Select data directory [1-$((i-1))]:${RST} "
    read -r choice

    if [[ "$choice" == "b" || "$choice" == "B" ]]; then
        return 2
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice < i )); then
        BITCOIN_DATA_DIR="${found_array[$((choice-1))]}"
        echo ""
        if prompt_yn "Use $BITCOIN_DATA_DIR as data directory?"; then
            msg_ok "Selected: $BITCOIN_DATA_DIR"
            return 0
        else
            return 1
        fi
    fi

    msg_err "Invalid selection"
    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# COOKIE AUTH DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

get_network_datadir() {
    local base="$1"
    local network="$2"

    case "$network" in
        test|testnet) echo "$base/testnet3" ;;
        signet)       echo "$base/signet" ;;
        regtest)      echo "$base/regtest" ;;
        *)            echo "$base" ;;
    esac
}

find_cookie() {
    [[ -n "$BITCOIN_RPC_COOKIE_FILE" && -f "$BITCOIN_RPC_COOKIE_FILE" ]] && return 0

    local effective_datadir
    effective_datadir=$(get_network_datadir "$BITCOIN_DATA_DIR" "$BITCOIN_NETWORK")

    if [[ -f "$effective_datadir/.cookie" ]]; then
        BITCOIN_RPC_COOKIE_FILE="$effective_datadir/.cookie"
        return 0
    fi

    [[ -f "$BITCOIN_DATA_DIR/.cookie" ]] && BITCOIN_RPC_COOKIE_FILE="$BITCOIN_DATA_DIR/.cookie" && return 0

    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL INPUT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

manual_enter_conf() {
    echo ""
    echo -e "${T_DIM}Enter the path to your bitcoin.conf file.${RST}"
    echo -e "${T_DIM}(You may enter * to go back, or just press Enter to use the example path)${RST}"
    echo ""

    # Try to detect a default conf path
    local default_conf=""
    if [[ -f "/srv/bitcoin/bitcoin.conf" ]]; then
        default_conf="/srv/bitcoin/bitcoin.conf"
    elif [[ -f "$HOME/.bitcoin/bitcoin.conf" ]]; then
        default_conf="$HOME/.bitcoin/bitcoin.conf"
    elif [[ -f "/etc/bitcoin/bitcoin.conf" ]]; then
        default_conf="/etc/bitcoin/bitcoin.conf"
    fi

    local input
    if [[ -n "$default_conf" ]]; then
        echo -en "${T_INFO}Location of bitcoin.conf${RST} ${T_DIM}(ex: ${default_conf}):${RST} "
    else
        echo -en "${T_INFO}Location of bitcoin.conf:${RST} "
    fi
    read -r input

    # Handle * to go back
    if [[ "$input" == "*" ]]; then
        return 2
    fi

    # Use default if just Enter pressed
    if [[ -z "$input" && -n "$default_conf" ]]; then
        input="$default_conf"
    fi

    if [[ -z "$input" ]]; then
        msg_err "Please enter a path"
        return 1
    fi

    input="${input/#\~/$HOME}"

    if [[ -f "$input" ]]; then
        BITCOIN_CONFIG_FILE="$input"
        msg_ok "Config file set: $BITCOIN_CONFIG_FILE"

        local conf_dir
        conf_dir=$(dirname "$input")
        if [[ -z "$BITCOIN_DATA_DIR" ]] && validate_datadir "$conf_dir"; then
            BITCOIN_DATA_DIR="$conf_dir"
            msg_ok "Also found datadir: $BITCOIN_DATA_DIR"
        fi
        return 0
    else
        msg_err "File not found: $input"
        return 1
    fi
}

manual_enter_datadir() {
    echo ""
    echo -e "${T_DIM}Enter the path to your Bitcoin Core data directory.${RST}"
    echo -e "${T_DIM}(You may enter * to go back, or just press Enter to use the example path)${RST}"
    echo ""

    # Try to detect a default datadir
    local default_datadir=""
    if [[ -n "$BITCOIN_CONFIG_FILE" ]]; then
        default_datadir=$(dirname "$BITCOIN_CONFIG_FILE")
    elif [[ -d "/srv/bitcoin" ]]; then
        default_datadir="/srv/bitcoin"
    elif [[ -d "$HOME/.bitcoin" ]]; then
        default_datadir="$HOME/.bitcoin"
    fi

    local input
    if [[ -n "$default_datadir" ]]; then
        echo -en "${T_INFO}Location of data directory${RST} ${T_DIM}(ex: ${default_datadir}):${RST} "
    else
        echo -en "${T_INFO}Location of data directory:${RST} "
    fi
    read -r input

    # Handle * to go back
    if [[ "$input" == "*" ]]; then
        return 2
    fi

    # Use default if just Enter pressed
    if [[ -z "$input" && -n "$default_datadir" ]]; then
        input="$default_datadir"
    fi

    if [[ -z "$input" ]]; then
        msg_err "Please enter a path"
        return 1
    fi

    input="${input/#\~/$HOME}"

    if validate_datadir "$input"; then
        BITCOIN_DATA_DIR="$input"
        msg_ok "Data directory set: $BITCOIN_DATA_DIR"

        if [[ -z "$BITCOIN_CONFIG_FILE" && -f "$input/bitcoin.conf" ]]; then
            BITCOIN_CONFIG_FILE="$input/bitcoin.conf"
            msg_ok "Also found config: $BITCOIN_CONFIG_FILE"
        fi
        return 0
    elif [[ -d "$input" ]]; then
        msg_warn "Directory exists but doesn't look like a Bitcoin datadir"
        if prompt_yn "Use it anyway?"; then
            BITCOIN_DATA_DIR="$input"
            return 0
        fi
        return 1
    else
        msg_err "Directory not found: $input"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# DISPLAY RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

display_detection_results() {
    echo ""
    echo -e "${T_SECONDARY}${BOLD}Found Settings:${RST}"
    echo ""

    print_kv "Bitcoin CLI" "${BITCOIN_CLI:-not found}" 18
    print_kv "Version" "${BITCOIN_CLI_VERSION:-unknown}" 18
    print_kv "Data Directory" "${BITCOIN_DATA_DIR:-not found}" 18
    print_kv "Config File" "${BITCOIN_CONFIG_FILE:-not found}" 18
    print_kv "Network" "${BITCOIN_NETWORK}" 18
    print_kv "RPC Host:Port" "${BITCOIN_RPC_HOST}:${BITCOIN_RPC_PORT}" 18

    if [[ -n "$BITCOIN_RPC_COOKIE_FILE" && -f "$BITCOIN_RPC_COOKIE_FILE" ]]; then
        print_kv "Auth Method" "Cookie" 18
        print_kv "Cookie File" "$BITCOIN_RPC_COOKIE_FILE" 18
    elif [[ -n "$BITCOIN_RPC_USER" ]]; then
        print_kv "Auth Method" "User/Password" 18
        print_kv "RPC User" "$BITCOIN_RPC_USER" 18
    else
        print_kv "Auth Method" "Default" 18
    fi

    if [[ "$node_running" -eq 1 ]]; then
        echo ""
        echo -e "  ${T_SUCCESS}${SYM_CHECK} bitcoind is running${RST}"
    fi

    echo ""
    echo -e "${T_DIM}Full CLI command:${RST}"
    echo -e "  ${BWHITE}$(get_bitcoin_cli_command)${RST}"
    echo ""
}

confirm_detection_results() {
    # Auto mode: skip prompt and auto-save
    if [[ "${BPM_AUTO_DETECT:-0}" == "1" ]]; then
        save_config
        msg_ok "Configuration saved!"
        return 0
    fi

    echo ""
    echo -e "${T_WARN}?${RST} Choose an option:"
    echo ""
    echo -e "  ${T_INFO}y)${RST} Use the detected settings, and continue to the main menu"
    echo -e "  ${T_INFO}n)${RST} I would like to manually enter my Bitcoin Core settings"
    echo -e "  ${T_ERROR}q)${RST} Quit"
    echo ""

    while true; do
        echo -en "${T_DIM}Choice [y/n/q]:${RST} "
        read -r confirm_choice

        case "$confirm_choice" in
            y|Y|yes|Yes)
                save_config
                msg_ok "Configuration saved!"
                return 0
                ;;
            n|N|no|No)
                # Run manual configuration
                echo ""
                echo -e "${T_SECONDARY}${BOLD}Manual Configuration${RST}"

                while true; do
                    manual_enter_conf
                    local result=$?
                    [[ $result -eq 0 ]] && break
                    [[ $result -eq 2 ]] && return 1
                done

                if [[ -z "$BITCOIN_DATA_DIR" ]]; then
                    while true; do
                        manual_enter_datadir
                        local result=$?
                        [[ $result -eq 0 ]] && break
                        [[ $result -eq 2 ]] && break
                    done
                fi

                # Re-detect remaining settings
                echo ""
                echo -e "${T_SECONDARY}${BOLD}Auto-detecting remaining settings...${RST}"
                detect_bitcoin_cli
                if [[ -n "$BITCOIN_CONFIG_FILE" ]]; then
                    parse_conf_file "$BITCOIN_CONFIG_FILE"
                fi
                find_cookie
                if [[ -n "$BITCOIN_CLI" ]]; then
                    msg_ok "Found bitcoin-cli: $BITCOIN_CLI"
                fi
                if [[ -n "$BITCOIN_RPC_COOKIE_FILE" && -f "$BITCOIN_RPC_COOKIE_FILE" ]]; then
                    msg_ok "Found cookie auth: $BITCOIN_RPC_COOKIE_FILE"
                fi

                # Test RPC
                echo ""
                start_spinner "Testing RPC connection"
                if test_rpc; then
                    stop_spinner 0 "RPC connection successful!"
                else
                    stop_spinner 1 "RPC connection failed"
                    msg_warn "bitcoind may not be running"
                fi

                save_config
                msg_ok "Configuration saved!"
                return 0
                ;;
            q|Q|quit|Quit)
                msg_info "Goodbye!"
                exit 0
                ;;
            "")
                msg_warn "Please enter y, n, or q"
                ;;
            *)
                msg_warn "Invalid option. Please enter y, n, or q"
                ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DETECTION FLOW
# ═══════════════════════════════════════════════════════════════════════════════

run_detection() {
    echo ""
    echo -e "${T_SECONDARY}${BOLD}Bitcoin Core Detection${RST}"
    echo ""

    local goto_rpc_test=0
    local goto_manual=0

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: Check cache
    # ─────────────────────────────────────────────────────────────────────────
    echo -e "${T_DIM}Step 1: Checking cached configuration...${RST}"

    if load_config; then
        msg_ok "Found cached configuration"
        display_cached_config

        echo -e "${T_WARN}?${RST} Is this configuration correct?"
        echo ""
        echo -e "  ${T_INFO}1)${RST} Yes, use this configuration"
        echo -e "  ${T_INFO}2)${RST} No, run auto-detection"
        echo -e "  ${T_INFO}3)${RST} No, enter settings manually"
        echo ""

        local choice
        echo -en "${T_DIM}Choice [1-3]:${RST} "
        read -r choice

        case "$choice" in
            1)
                msg_ok "Using cached configuration"
                detect_bitcoin_cli
                find_cookie
                if [[ -n "$BITCOIN_CONFIG_FILE" ]]; then
                    parse_conf_file "$BITCOIN_CONFIG_FILE"
                fi
                goto_rpc_test=1
                ;;
            2)
                msg_info "Running auto-detection..."
                clear_config
                ;;
            3)
                msg_info "Manual configuration..."
                clear_config
                goto_manual=1
                ;;
            *)
                msg_info "Running auto-detection..."
                clear_config
                ;;
        esac
    else
        msg_info "No cached configuration found"
    fi
    echo ""

    # Skip detection if using cache
    if [[ "${goto_rpc_test}" -eq 1 ]]; then
        :
    elif [[ "${goto_manual}" -eq 1 ]]; then
        # Manual configuration flow
        echo -e "${T_SECONDARY}${BOLD}Manual Configuration${RST}"
        echo ""

        while true; do
            manual_enter_conf
            local result=$?
            [[ $result -eq 0 ]] && break
            [[ $result -eq 2 ]] && break
        done

        if [[ -z "$BITCOIN_DATA_DIR" ]]; then
            while true; do
                manual_enter_datadir
                local result=$?
                [[ $result -eq 0 ]] && break
                [[ $result -eq 2 ]] && break
            done
        fi

        detect_bitcoin_cli
        echo ""
    else
        # ─────────────────────────────────────────────────────────────────────
        # STEP 2: Check running process
        # ─────────────────────────────────────────────────────────────────────
        echo -e "${T_DIM}Step 2: Checking running processes...${RST}"

        start_spinner "Scanning for bitcoind process"
        if detect_running_process; then
            stop_spinner 0 "Found running bitcoind (PID: $(pgrep bitcoind | head -1))"
            [[ -n "$BITCOIN_DATA_DIR" ]] && msg_ok "Detected datadir: $BITCOIN_DATA_DIR"
            [[ -n "$BITCOIN_CONFIG_FILE" ]] && msg_ok "Detected conf: $BITCOIN_CONFIG_FILE"
        else
            stop_spinner 0 "bitcoind not running"

            start_spinner "Checking systemd services"
            if detect_systemd_service; then
                stop_spinner 0 "Found configuration from systemd service"
                [[ -n "$BITCOIN_DATA_DIR" ]] && msg_ok "Datadir: $BITCOIN_DATA_DIR"
                [[ -n "$BITCOIN_CONFIG_FILE" ]] && msg_ok "Conf: $BITCOIN_CONFIG_FILE"
            else
                stop_spinner 0 "No systemd bitcoin service found"
            fi
        fi
        echo ""

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3: Find config file
        # ─────────────────────────────────────────────────────────────────────
        echo -e "${T_DIM}Step 3: Locating config file...${RST}"

        start_spinner "Searching common locations"
        if find_conf_file; then
            stop_spinner 0 "Found: $BITCOIN_CONFIG_FILE"
        else
            stop_spinner 1 "Config file not found in common locations"

            echo ""
            echo -e "${T_WARN}?${RST} How would you like to proceed?"
            echo ""
            echo -e "  ${T_INFO}1)${RST} Search entire system ${T_DIM}(may take a LONG time)${RST}"
            echo -e "  ${T_INFO}2)${RST} Enter path manually"
            echo -e "  ${T_INFO}3)${RST} Skip ${T_DIM}(continue without config file)${RST}"
            echo ""

            local choice
            echo -en "${T_DIM}Choice [1-3]:${RST} "
            read -r choice

            case "$choice" in
                1) search_conf_file ;;
                2)
                    while true; do
                        manual_enter_conf
                        local result=$?
                        [[ $result -eq 0 ]] && break
                        [[ $result -eq 2 ]] && break
                    done
                    ;;
                3) msg_info "Skipping config file" ;;
            esac
        fi

        if [[ -n "$BITCOIN_CONFIG_FILE" && -f "$BITCOIN_CONFIG_FILE" ]]; then
            msg_info "Parsing config file..."
            parse_conf_file "$BITCOIN_CONFIG_FILE"
            [[ -n "$BITCOIN_DATA_DIR" ]] && msg_ok "Found datadir in config: $BITCOIN_DATA_DIR"
        fi
        echo ""

        # ─────────────────────────────────────────────────────────────────────
        # STEP 4: Find data directory
        # ─────────────────────────────────────────────────────────────────────
        echo -e "${T_DIM}Step 4: Locating data directory...${RST}"

        if [[ -n "$BITCOIN_DATA_DIR" ]] && validate_datadir "$BITCOIN_DATA_DIR"; then
            msg_ok "Already found: $BITCOIN_DATA_DIR"
        else
            start_spinner "Searching common locations"
            if find_datadir; then
                stop_spinner 0 "Found: $BITCOIN_DATA_DIR"
            else
                stop_spinner 1 "Data directory not found in common locations"

                echo ""
                echo -e "${T_WARN}?${RST} How would you like to proceed?"
                echo ""
                echo -e "  ${T_INFO}1)${RST} Search entire system for blockchain data ${T_DIM}(VERY slow!)${RST}"
                echo -e "  ${T_INFO}2)${RST} Enter path manually"
                echo -e "  ${T_INFO}3)${RST} Skip ${T_DIM}(continue without datadir)${RST}"
                echo ""

                local choice
                echo -en "${T_DIM}Choice [1-3]:${RST} "
                read -r choice

                case "$choice" in
                    1) search_datadir ;;
                    2)
                        while true; do
                            manual_enter_datadir
                            local result=$?
                            [[ $result -eq 0 ]] && break
                            [[ $result -eq 2 ]] && break
                        done
                        ;;
                    3) msg_info "Skipping data directory" ;;
                esac
            fi
        fi
        echo ""

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5: Find bitcoin-cli
        # ─────────────────────────────────────────────────────────────────────
        echo -e "${T_DIM}Step 5: Testing bitcoin-cli...${RST}"

        start_spinner "Checking bitcoin-cli"
        if detect_bitcoin_cli; then
            stop_spinner 0 "Found: $BITCOIN_CLI ($BITCOIN_CLI_VERSION)"
        else
            stop_spinner 1 "bitcoin-cli not found"
            msg_err "Bitcoin Core does not appear to be installed"
            return 1
        fi
        echo ""
    fi

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6: Find cookie auth
    # ─────────────────────────────────────────────────────────────────────────
    echo -e "${T_DIM}Step 6: Checking authentication...${RST}"

    find_cookie
    if [[ -n "$BITCOIN_RPC_COOKIE_FILE" && -f "$BITCOIN_RPC_COOKIE_FILE" ]]; then
        msg_ok "Cookie auth: $BITCOIN_RPC_COOKIE_FILE"
    elif [[ -n "$BITCOIN_RPC_USER" ]]; then
        msg_ok "User/password auth configured"
    else
        msg_info "Using default authentication"
    fi
    echo ""

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7: Test RPC connection
    # ─────────────────────────────────────────────────────────────────────────
    echo -e "${T_DIM}Step 7: Testing RPC connection...${RST}"

    start_spinner "Connecting to Bitcoin Core"
    if test_rpc; then
        stop_spinner 0 "RPC connection successful!"
    else
        stop_spinner 1 "RPC connection failed"
        msg_warn "Could not connect to Bitcoin Core RPC"
        msg_info "bitcoind may not be running, or auth settings may be incorrect"
    fi
    echo ""

    # ─────────────────────────────────────────────────────────────────────────
    # Display results and ask for confirmation
    # ─────────────────────────────────────────────────────────────────────────
    display_detection_results
    confirm_detection_results

    return 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

# If run directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_detection
    if [[ "${BPM_AUTO_DETECT:-0}" != "1" ]]; then
        echo ""
        echo -en "${T_DIM}Press Enter to continue...${RST}"
        read -r
    fi
fi
