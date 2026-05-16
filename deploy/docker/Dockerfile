# docker build -t hgjazhgj/alas:latest .
# docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm hgjazhgj/alas

# 由于 Python 3.14 官方 Docker 镜像尚未发布，我们从 Debian 基础镜像构建
FROM debian:bookworm-slim as python-builder

ARG PYTHON_VERSION=3.14.0a7
ARG HTTP_PROXY=
ARG HTTPS_PROXY=

ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}

# 安装构建 Python 所需的依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libffi-dev \
    liblzma-dev \
    tk-dev \
    uuid-dev \
    && rm -rf /var/lib/apt/lists/*

# 下载并编译 Python 3.14
RUN wget https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz \
    && tar -xf Python-${PYTHON_VERSION}.tar.xz \
    && cd Python-${PYTHON_VERSION} \
    && ./configure --enable-optimizations --with-lto --prefix=/usr/local \
    && make -j$(nproc) \
    && make install \
    && cd .. \
    && rm -rf Python-${PYTHON_VERSION} Python-${PYTHON_VERSION}.tar.xz

# 最终镜像
FROM debian:bookworm-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=127.0.0.1,localhost

ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV PATH=/usr/local/bin:$PATH

# 从构建阶段复制 Python
COPY --from=python-builder /usr/local /usr/local

WORKDIR /app/AzurLaneAutoScript

COPY requirements.txt /tmp/requirements.txt

# 安装运行时依赖和 Python 包
RUN printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$HTTP_PROXY" "$HTTPS_PROXY" > /etc/apt/apt.conf.d/99proxy \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        adb \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        openssh-client \
        build-essential \
        pkg-config \
        libavformat-dev \
        libavcodec-dev \
        libavdevice-dev \
        libavutil-dev \
        libswscale-dev \
        libswresample-dev \
        libavfilter-dev \
        libssl3 \
        libsqlite3-0 \
        libbz2-1.0 \
        libreadline8 \
        libffi8 \
        liblzma5 \
    && git config --global --add safe.directory '*' \
    && git config --global http.proxy "$HTTP_PROXY" \
    && git config --global https.proxy "$HTTPS_PROXY" \
    && python3.14 -m pip install --upgrade pip \
    && python3.14 -m pip install Cython==0.29.37 \
    && python3.14 -m pip install av==10.0.0 --no-build-isolation \
    && python3.14 -m pip install -r /tmp/requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm /tmp/requirements.txt \
    && rm -r ~/.cache/pip

# 创建 python 符号链接
RUN ln -sf /usr/local/bin/python3.14 /usr/local/bin/python \
    && ln -sf /usr/local/bin/python3.14 /usr/local/bin/python3

CMD ["python", "gui.py"]
