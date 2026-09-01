FROM alpine:3.22

LABEL org.opencontainers.image.title="Bitcoin Peer Map" \
      org.opencontainers.image.source="https://github.com/spyhunter493/bitcoin-peer-map"

RUN apk add --no-cache \
        bitcoin-cli \
        ca-certificates \
        iproute2 \
        procps \
        python3 \
        py3-pip \
        py3-virtualenv \
    && addgroup -S bpm \
    && adduser -S -D -H -h /opt/bitcoin-peer-map -G bpm bpm \
    && python3 -m venv /opt/venv

WORKDIR /opt/bitcoin-peer-map

COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY --chown=bpm:bpm . /opt/bitcoin-peer-map

RUN chmod 0755 /opt/bitcoin-peer-map/docker-entrypoint.sh \
    && mkdir -p /var/lib/bitcoin-peer-map /run/bitcoin-peer-map \
    && chown -R bpm:bpm /opt/bitcoin-peer-map /opt/venv /var/lib/bitcoin-peer-map /run/bitcoin-peer-map

USER bpm

ENV BPM_DATA_DIR=/var/lib/bitcoin-peer-map

EXPOSE 58333
VOLUME ["/var/lib/bitcoin-peer-map"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD /opt/venv/bin/python3 -c "import os, urllib.request; port = os.environ.get('BPM_LISTEN_PORT', '58333'); urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3).read(1)"

ENTRYPOINT ["/opt/bitcoin-peer-map/docker-entrypoint.sh"]
