# syntax=docker/dockerfile:1.6
FROM --platform=linux/arm64 debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-venv \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV ELAN_HOME=/opt/elan
ENV PATH=$ELAN_HOME/bin:$PATH
RUN curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none --no-modify-path

ARG MATHLIB_REV=816c6385c237d331828882f9878e5ebfc65e10e3

WORKDIR /opt/mathlib4
RUN git init -q . \
    && git remote add origin https://github.com/leanprover-community/mathlib4.git \
    && git fetch --depth 1 origin ${MATHLIB_REV} \
    && git checkout FETCH_HEAD

RUN lake exe cache get

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN pip install --no-cache-dir redis==7.4.0 boto3==1.43.6

WORKDIR /opt/verifier
COPY verifier_worker.py /opt/verifier/verifier_worker.py

CMD ["python3", "/opt/verifier/verifier_worker.py"]
