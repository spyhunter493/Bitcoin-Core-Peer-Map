FROM alpine:3.22

RUN apk add --no-cache \
        bitcoin-cli \
        ca-certificates \
        iproute2 \
        procps \
        python3 \
        py3-pip \
        py3-virtualenv \
    && addgroup -S mbcore \
    && adduser -S -D -H -h /opt/mbcore -G mbcore mbcore \
    && python3 -m venv /opt/venv

WORKDIR /opt/mbcore

COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY --chown=mbcore:mbcore . /opt/mbcore

RUN chmod 0755 /opt/mbcore/docker-entrypoint.sh \
    && mkdir -p /opt/mbcore/data \
    && chown -R mbcore:mbcore /opt/mbcore /opt/venv

USER mbcore

EXPOSE 58333
VOLUME ["/opt/mbcore/data"]

ENTRYPOINT ["/opt/mbcore/docker-entrypoint.sh"]
