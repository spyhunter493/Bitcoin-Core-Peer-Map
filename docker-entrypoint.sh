#!/bin/sh
set -eu

DATA_DIR=/opt/mbcore/data
CONFIG_FILE="$DATA_DIR/config.conf"
RUNTIME_DIR=/tmp/mbcore
BITCOIN_CONF="$RUNTIME_DIR/bitcoin.conf"

die() {
    echo "MBCore: $*" >&2
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
MBTC_NETWORK=${MBTC_NETWORK:-main}
MBTC_WEB_PORT=${MBTC_WEB_PORT:-58333}
MBTC_WEB_BIND=${MBTC_WEB_BIND:-0.0.0.0}

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
case "$MBTC_WEB_PORT" in *[!0-9]*|'') die "MBTC_WEB_PORT must be numeric" ;; esac
case "$MBTC_NETWORK" in main|test|signet|regtest) ;; *) die "MBTC_NETWORK must be main, test, signet, or regtest" ;; esac
case "$MBTC_WEB_BIND" in 0.0.0.0|127.0.0.1) ;; *) die "MBTC_WEB_BIND must be 0.0.0.0 or 127.0.0.1" ;; esac

for variable in BITCOIN_RPC_HOST BITCOIN_RPC_USER BITCOIN_RPC_PASSWORD; do
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

if [ -n "${GEO_DB_ENABLED+x}" ]; then
    geo_db_enabled=$GEO_DB_ENABLED
else
    geo_db_enabled=$(config_value GEO_DB_ENABLED 2>/dev/null || printf 'true')
fi

if [ -n "${GEO_DB_AUTO_UPDATE+x}" ]; then
    geo_db_auto_update=$GEO_DB_AUTO_UPDATE
else
    geo_db_auto_update=$(config_value GEO_DB_AUTO_UPDATE 2>/dev/null || printf 'true')
fi

case "$geo_db_enabled" in true|false) ;; *) die "GEO_DB_ENABLED must be true or false" ;; esac
case "$geo_db_auto_update" in true|false) ;; *) die "GEO_DB_AUTO_UPDATE must be true or false" ;; esac

managed_keys='^(MBTC_CLI_PATH|MBTC_DATADIR|MBTC_CONF|MBTC_NETWORK|MBTC_RPC_HOST|MBTC_RPC_PORT|MBTC_RPC_USER|MBTC_COOKIE_PATH|MBTC_WEB_PORT|MBTC_WEB_BIND|MBTC_CONFIGURED|GEO_DB_ENABLED|GEO_DB_AUTO_UPDATE)='
temp_config=$(mktemp "$DATA_DIR/.config.conf.XXXXXX")
if [ -f "$CONFIG_FILE" ]; then
    awk -v managed="$managed_keys" '$0 !~ managed' "$CONFIG_FILE" > "$temp_config"
fi

cat >> "$temp_config" <<EOF
MBTC_CLI_PATH="/usr/bin/bitcoin-cli"
MBTC_DATADIR=""
MBTC_CONF="$(quote_config "$BITCOIN_CONF")"
MBTC_NETWORK="$(quote_config "$MBTC_NETWORK")"

MBTC_RPC_HOST="$(quote_config "$BITCOIN_RPC_HOST")"
MBTC_RPC_PORT="$(quote_config "$BITCOIN_RPC_PORT")"
MBTC_RPC_USER="$(quote_config "$BITCOIN_RPC_USER")"
MBTC_COOKIE_PATH=""

MBTC_WEB_PORT="$(quote_config "$MBTC_WEB_PORT")"
MBTC_WEB_BIND="$(quote_config "$MBTC_WEB_BIND")"

MBTC_CONFIGURED=1

GEO_DB_ENABLED="$geo_db_enabled"
GEO_DB_AUTO_UPDATE="$geo_db_auto_update"
EOF

chmod 0600 "$temp_config"
mv "$temp_config" "$CONFIG_FILE"

case "$MBTC_NETWORK" in
    main) network_option='' ;;
    test) network_option='-testnet' ;;
    signet) network_option='-signet' ;;
    regtest) network_option='-regtest' ;;
esac

echo "MBCore: checking Bitcoin RPC at $BITCOIN_RPC_HOST:$BITCOIN_RPC_PORT ($MBTC_NETWORK)"
if ! /usr/bin/bitcoin-cli -conf="$BITCOIN_CONF" $network_option getnetworkinfo >/dev/null 2>&1; then
    die "Bitcoin RPC connectivity check failed for $BITCOIN_RPC_HOST:$BITCOIN_RPC_PORT; check the RPC address, network, credentials, rpcbind, and rpcallowip settings"
fi

echo "MBCore: Bitcoin RPC is available; starting dashboard on $MBTC_WEB_BIND:$MBTC_WEB_PORT"
exec /opt/venv/bin/python3 /opt/mbcore/web/MBCoreServer.py

