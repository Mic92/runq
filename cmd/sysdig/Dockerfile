FROM alpine

RUN apk add \
    cmake \
    make \
    gcc \
    g++ \
	pkgconfig \
    linux-headers \
	elfutils-dev \
	libelf-static \
	perl \
	patch \
    git

ENV SYSDIG_VERSION 0.27.1

RUN mkdir -p /src/build && \
    wget https://github.com/draios/sysdig/archive/refs/tags/${SYSDIG_VERSION}.tar.gz -O /tmp/sysdig.tar.gz && \
    tar -C /src --strip-components=1 -xf /tmp/sysdig.tar.gz && \
    rm /tmp/sysdig.tar.gz

# we also need to hot patch grpc here to fix.
RUN cd /src/build && \
    cmake -DCMAKE_BUILD_TYPE=Release -DCREATE_TEST_TARGETS=OFF -DBUILD_DRIVER=OFF -DMUSL_OPTIMIZED_BUILD=On .. && \
    make -j$(nproc) jq grpc || \
    sed -i -e '/gettid(void)/d' ./grpc-prefix/src/grpc/src/core/lib/support/log_linux.cc && \
    make -j$(nproc)
