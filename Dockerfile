FROM python:3.12-alpine3.22

ARG BPM_BUILD_REVISION=unknown

LABEL org.opencontainers.image.title="Bitcoin Peer Map" \
      org.opencontainers.image.source="https://github.com/spyhunter493/bitcoin-peer-map" \
      org.opencontainers.image.revision="${BPM_BUILD_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BPM_DATA_DIR=/var/lib/bitcoin-peer-map \
    BPM_BUILD_REVISION=${BPM_BUILD_REVISION}

RUN addgroup -S -g 10001 bpm \
    && adduser -S -D -H -u 10001 -h /app -G bpm bpm

WORKDIR /app

COPY requirements.txt ./

RUN python -m pip install --no-cache-dir --requirement requirements.txt \
    && mkdir -p /var/lib/bitcoin-peer-map \
    && chown -R bpm:bpm /var/lib/bitcoin-peer-map

COPY --chown=bpm:bpm src ./src

USER bpm

EXPOSE 58333
VOLUME ["/var/lib/bitcoin-peer-map"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('BPM_LISTEN_PORT', '58333'); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).read(1)"

CMD ["python", "src/main.py"]
