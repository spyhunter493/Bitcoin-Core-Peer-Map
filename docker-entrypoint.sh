#!/bin/sh
set -eu

BPM_DATA_DIR=${BPM_DATA_DIR:-/var/lib/bitcoin-peer-map}
DATA_DIR=$BPM_DATA_DIR
CONFIG_FILE="$DATA_DIR/config.conf"
RUNTIME_DIR=/run/bitcoin-peer-map
BITCOIN_CONF="$RUNTIME_DIR/bitcoin.conf"

die() {
    echo "Bitcoin Peer Map: $*" >&2
    exit 1
}

require_single_line() {
    name=$1
    value=$2
    case "$value" in
        *"
"*) die "$name must not contain a newline" ;;
    esac
}

config_value() {
    key=$1
    [ -f "$CONFIG_FILE" ] || return 1
    awk -F= -v key="$key" '
        $1 == key {
            value = substr($0, index($0, "=") + 1)
            gsub(/^[[:space:]]*[\047\042]|[\047\042][[:space:]]*$/, "", value)
            print value
            found = 1
            exit
        }
        END { if (!found) exit 1 }
    ' "$CONFIG_FILE"
}

quote_config() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

BITCOIN_RPC_HOST=${BITCOIN_RPC_HOST:-bitcoin}
BITCOIN_RPC_PORT=${BITCOIN_RPC_PORT:-8332}
BITCOIN_RPC_USER=${BITCOIN_RPC_USER:-}
BITCOIN_NETWORK=${BITCOIN_NETWORK:-main}
BPM_LISTEN_PORT=${BPM_LISTEN_PORT:-58333}
BPM_LISTEN_ADDRESS=${BPM_LISTEN_ADDRESS:-0.0.0.0}

[ -n "$BITCOIN_RPC_USER" ] || die "BITCOIN_RPC_USER is required"

if [ -n "${BITCOIN_RPC_PASSWORD:-}" ] && [ -n "${BITCOIN_RPC_PASSWORD_FILE:-}" ]; then
    die "set only one of BITCOIN_RPC_PASSWORD or BITCOIN_RPC_PASSWORD_FILE"
fi

if [ -n "${BITCOIN_RPC_PASSWORD_FILE:-}" ]; then
    [ -r "$BITCOIN_RPC_PASSWORD_FILE" ] || die "BITCOIN_RPC_PASSWORD_FILE is not readable: $BITCOIN_RPC_PASSWORD_FILE"
    BITCOIN_RPC_PASSWORD=$(cat "$BITCOIN_RPC_PASSWORD_FILE")
else
    BITCOIN_RPC_PASSWORD=${BITCOIN_RPC_PASSWORD:-}
fi

[ -n "$BITCOIN_RPC_PASSWORD" ] || die "BITCOIN_RPC_PASSWORD or BITCOIN_RPC_PASSWORD_FILE is required"

case "$BITCOIN_RPC_PORT" in *[!0-9]*|'') die "BITCOIN_RPC_PORT must be numeric" ;; esac
case "$BPM_LISTEN_PORT" in *[!0-9]*|'') die "BPM_LISTEN_PORT must be numeric" ;; esac
case "$BITCOIN_NETWORK" in main|test|signet|regtest) ;; *) die "BITCOIN_NETWORK must be main, test, signet, or regtest" ;; esac
case "$BPM_LISTEN_ADDRESS" in 0.0.0.0|127.0.0.1) ;; *) die "BPM_LISTEN_ADDRESS must be 0.0.0.0 or 127.0.0.1" ;; esac

for variable in BITCOIN_RPC_HOST BITCOIN_RPC_USER BITCOIN_RPC_PASSWORD BPM_DATA_DIR; do
    eval "value=\${$variable}"
    require_single_line "$variable" "$value"
done

mkdir -p "$DATA_DIR" "$RUNTIME_DIR"
chmod 0700 "$RUNTIME_DIR"

umask 077
cat > "$BITCOIN_CONF" <<EOF
rpcconnect=$BITCOIN_RPC_HOST
rpcport=$BITCOIN_RPC_PORT
rpcuser=$BITCOIN_RPC_USER
rpcpassword=$BITCOIN_RPC_PASSWORD
EOF
chmod 0600 "$BITCOIN_CONF"

if [ -n "${BPM_GEOIP_ENABLED:-}" ]; then
    geoip_enabled=$BPM_GEOIP_ENABLED
else
    geoip_enabled=$(config_value BPM_GEOIP_ENABLED 2>/dev/null || printf 'true')
fi

if [ -n "${BPM_GEOIP_AUTO_UPDATE:-}" ]; then
    geoip_auto_update=$BPM_GEOIP_AUTO_UPDATE
else
    geoip_auto_update=$(config_value BPM_GEOIP_AUTO_UPDATE 2>/dev/null || printf 'true')
fi

case "$geoip_enabled" in true|false) ;; *) die "BPM_GEOIP_ENABLED must be true or false" ;; esac
case "$geoip_auto_update" in true|false) ;; *) die "BPM_GEOIP_AUTO_UPDATE must be true or false" ;; esac

managed_keys='^(BITCOIN_CLI|BITCOIN_DATA_DIR|BITCOIN_CONFIG_FILE|BITCOIN_NETWORK|BITCOIN_RPC_HOST|BITCOIN_RPC_PORT|BITCOIN_RPC_USER|BITCOIN_RPC_COOKIE_FILE|BPM_LISTEN_PORT|BPM_LISTEN_ADDRESS|BPM_GEOIP_ENABLED|BPM_GEOIP_AUTO_UPDATE)$'
temp_config=$(mktemp "$DATA_DIR/.config.conf.XXXXXX")
if [ -f "$CONFIG_FILE" ]; then
    awk -F= -v managed="$managed_keys" '$1 !~ managed && $1 ~ /^[A-Z][A-Z0-9_]*$/' "$CONFIG_FILE" > "$temp_config"
fi

cat >> "$temp_config" <<EOF
BITCOIN_CLI="/usr/bin/bitcoin-cli"
BITCOIN_DATA_DIR=""
BITCOIN_CONFIG_FILE="$(quote_config "$BITCOIN_CONF")"
BITCOIN_NETWORK="$(quote_config "$BITCOIN_NETWORK")"
BITCOIN_RPC_HOST="$(quote_config "$BITCOIN_RPC_HOST")"
BITCOIN_RPC_PORT="$(quote_config "$BITCOIN_RPC_PORT")"
BITCOIN_RPC_USER="$(quote_config "$BITCOIN_RPC_USER")"
BITCOIN_RPC_COOKIE_FILE=""
BPM_LISTEN_PORT="$(quote_config "$BPM_LISTEN_PORT")"
BPM_LISTEN_ADDRESS="$(quote_config "$BPM_LISTEN_ADDRESS")"
BPM_GEOIP_ENABLED="$geoip_enabled"
BPM_GEOIP_AUTO_UPDATE="$geoip_auto_update"
EOF

chmod 0600 "$temp_config"
mv "$temp_config" "$CONFIG_FILE"

case "$BITCOIN_NETWORK" in
    main) network_option='' ;;
    test) network_option='-testnet' ;;
    signet) network_option='-signet' ;;
    regtest) network_option='-regtest' ;;
esac

echo "Bitcoin Peer Map: checking Bitcoin RPC at $BITCOIN_RPC_HOST:$BITCOIN_RPC_PORT ($BITCOIN_NETWORK)"
set -- /usr/bin/bitcoin-cli "-conf=$BITCOIN_CONF"
if [ -n "$network_option" ]; then
    set -- "$@" "$network_option"
fi
if ! "$@" getnetworkinfo >/dev/null 2>&1; then
    die "Bitcoin RPC connectivity check failed for $BITCOIN_RPC_HOST:$BITCOIN_RPC_PORT; check the RPC address, network, credentials, rpcbind, and rpcallowip settings"
fi

export BPM_DATA_DIR BPM_LISTEN_PORT BPM_LISTEN_ADDRESS
echo "Bitcoin Peer Map: Bitcoin RPC is available; starting dashboard on $BPM_LISTEN_ADDRESS:$BPM_LISTEN_PORT"
exec /opt/venv/bin/python3 -m bitcoin_peer_map.server
