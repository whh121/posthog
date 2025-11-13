# PostHog Dockerfile 详细解读

本文档详细解释 PostHog 自托管生产环境 Dockerfile 的每个部分，帮助理解镜像构建的完整流程。

---

## 文件概述

这是一个**多阶段构建（Multi-stage Build）** Dockerfile，用于生产环境的自托管部署。

### 构建阶段
1. **frontend-build**: 构建前端静态资源（React + TypeScript）
2. **plugin-server-build**: 构建 plugin-server（Node.js 应用）及其依赖
3. **posthog-build**: 构建 Django 应用依赖和静态文件
4. **fetch-geoip-db**: 下载 GeoIP 地理位置数据库
5. **最终阶段**: 组装所有构建产物，创建运行时镜像

### 多阶段构建的优势
- **减小镜像体积**: 只保留运行时需要的文件，构建工具不包含在最终镜像
- **并行构建**: 不同阶段可以并行执行，提高构建速度
- **缓存优化**: 每个阶段独立缓存，未变化的层可以重用
- **安全性**: 构建工具和源代码不包含在生产镜像中

---

## 阶段 1: frontend-build - 前端构建

```dockerfile
FROM node:22.17.1-bookworm-slim AS frontend-build
```
**第 24 行**: 基于 Node.js 22.17.1（Debian Bookworm slim 版本）
- `bookworm-slim`: Debian 12 的精简版本，减小镜像体积
- `AS frontend-build`: 命名这个阶段，后续可引用

```dockerfile
WORKDIR /code
```
**第 25 行**: 设置工作目录为 `/code`，所有后续命令在此目录执行

```dockerfile
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
```
**第 26 行**: 设置 shell 的严格模式
- `-e`: 任何命令失败立即退出
- `-o pipefail`: 管道中任何命令失败都会导致整个管道失败
- `-c`: 执行字符串命令

### 复制配置文件

```dockerfile
COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
```
**第 28 行**: 复制根级别的配置文件
- `turbo.json`: Turborepo 单体仓库构建配置
- `package.json`: npm 包定义
- `pnpm-lock.yaml`: pnpm 的锁文件（确保依赖版本一致）
- `pnpm-workspace.yaml`: pnpm 工作区配置
- `tsconfig.json`: TypeScript 编译配置

```dockerfile
COPY frontend/package.json frontend/
COPY frontend/bin/ frontend/bin/
COPY bin/ bin/
COPY patches/ patches/
COPY common/hogvm/typescript/ common/hogvm/typescript/
COPY common/esbuilder/ common/esbuilder/
COPY common/tailwind/ common/tailwind/
COPY products/ products/
COPY ee/frontend/ ee/frontend/
```
**第 29-36 行**: 分别复制前端相关的目录
- `frontend/`: 前端主代码
- `bin/`: 构建脚本
- `patches/`: npm 包补丁（用 pnpm patch 修改第三方包）
- `common/`: 共享代码（HogVM、esbuilder、tailwind）
- `products/`: 产品功能模块
- `ee/frontend/`: 企业版前端代码

**为什么先复制 package.json 再复制源代码？**
- 利用 Docker 层缓存
- 如果 package.json 没变，依赖安装层可以被缓存
- 源代码变化不会触发依赖重新安装

### 安装依赖

```dockerfile
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && pnpm --version && \
    pnpm --filter=@posthog/frontend... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23
```
**第 38-40 行**: 使用 BuildKit 缓存挂载安装 npm 依赖
- `--mount=type=cache`: 使用 BuildKit 缓存挂载，跨构建复用下载的包
- `id=pnpm`: 缓存标识符
- `target=/tmp/pnpm-store-v23`: 缓存挂载点
- `corepack enable`: 启用 Node.js 内置的包管理器管理工具
- `pnpm --version`: 验证 pnpm 可用
- `--filter=@posthog/frontend...`: 只安装 frontend 及其依赖
- `--frozen-lockfile`: 使用锁文件，不更新（确保可重现构建）
- `--store-dir`: 指定 pnpm 存储目录

### 构建前端

```dockerfile
COPY frontend/ frontend/
```
**第 42 行**: 复制前端完整源代码（之前只复制了 package.json）

```dockerfile
RUN bin/turbo --filter=@posthog/frontend build
```
**第 43 行**: 使用 Turborepo 构建前端
- 输出目录: `frontend/dist/`
- 包含: HTML、CSS、JavaScript、静态资源

---

## 阶段 2: plugin-server-build - Plugin Server 构建

```dockerfile
FROM ghcr.io/posthog/rust-node-container:bookworm_rust_1.88-node_22.17.1 AS plugin-server-build
```
**第 48 行**: 基于 PostHog 自定义镜像，包含 Rust 和 Node.js
- 用于构建需要 Rust 和 Node.js 的混合项目（cyclotron）

### 安装系统依赖

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "wget" \
    "gnupg" \
```
**第 52-55 行**: 安装基础工具
- `wget`: 下载工具
- `gnupg`: GPG 签名验证工具
- `--no-install-recommends`: 不安装推荐的包，减小体积

```dockerfile
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
```
**第 57-59 行**: 添加 Confluent 的 APT 仓库
- Confluent 提供官方的 librdkafka（Kafka 客户端库）
- 下载并验证 GPG 密钥
- 添加软件源到 sources.list.d

```dockerfile
    apt-get update && \
    apt-get install -y --no-install-recommends \
    "make" \
    "g++" \
    "gcc" \
    "python3" \
    "librdkafka1=2.10.1-1.cflt~deb12" \
    "librdkafka++1=2.10.1-1.cflt~deb12" \
    "librdkafka-dev=2.10.1-1.cflt~deb12" \
    "libssl-dev=3.0.17-1~deb12u2" \
    "libssl3=3.0.17-1~deb12u2" \
    "zlib1g-dev" \
```
**第 60-71 行**: 安装编译工具和库
- `make, g++, gcc`: C/C++ 编译工具链
- `python3`: 某些 npm 包编译需要 Python
- `librdkafka*`: Kafka 客户端库（精确版本 2.10.1）
- `libssl*`: OpenSSL 库（安全版本）
- `zlib1g-dev`: 压缩库开发文件

```dockerfile
    && \
    rm -rf /var/lib/apt/lists/*
```
**第 72-73 行**: 清理 apt 缓存，减小镜像体积

### 复制项目文件

```dockerfile
WORKDIR /code
COPY turbo.json package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY ./bin/turbo ./bin/turbo
COPY ./patches ./patches
COPY ./rust ./rust
COPY ./common/esbuilder/ ./common/esbuilder/
COPY ./common/plugin_transpiler/ ./common/plugin_transpiler/
COPY ./common/hogvm/typescript/ ./common/hogvm/typescript/
COPY ./plugin-server/package.json ./plugin-server/tsconfig.json ./plugin-server/
```
**第 75-83 行**: 复制构建所需的配置和共享代码
- `rust/`: Rust 代码（cyclotron）
- `plugin_transpiler/`: 插件代码转译器
- `plugin-server/`: Plugin server 配置文件

### 环境配置

```dockerfile
ENV BUILD_LIBRDKAFKA=0
```
**第 87 行**: 使用系统的 librdkafka 而不是 npm 包内置版本
- 系统版本更稳定、性能更好
- 避免编译时间

### 安装 Node.js 依赖

```dockerfile
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-server... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-transpiler... install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 && \
    NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-transpiler build
```
**第 91-95 行**: 安装依赖并构建 plugin-transpiler
- `NODE_OPTIONS="--max-old-space-size=16384"`: 增加 Node.js 堆内存限制到 16GB
  - 防止大型项目构建时内存溢出
- 分别安装 plugin-server 和 plugin-transpiler 的依赖
- 构建 plugin-transpiler（会被 plugin-server 使用）

### 构建 Plugin Server

```dockerfile
COPY ./plugin-server/src/ ./plugin-server/src/
COPY ./plugin-server/tests/ ./plugin-server/tests/
COPY ./plugin-server/assets/ ./plugin-server/assets/
```
**第 101-103 行**: 复制 plugin-server 源代码
- 延迟到依赖安装后，利用缓存

```dockerfile
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/cyclotron build
```
**第 106 行**: 先构建 cyclotron（Rust + Node.js 混合项目）
- cyclotron 是任务调度系统

```dockerfile
RUN NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-server build
```
**第 109 行**: 构建 plugin-server
- 编译 TypeScript 到 JavaScript
- 输出到 `plugin-server/dist/`

### 安装生产依赖

```dockerfile
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23 \
    corepack enable && \
    NODE_OPTIONS="--max-old-space-size=16384" pnpm --filter=@posthog/plugin-server install --frozen-lockfile --store-dir /tmp/pnpm-store-v23 --prod && \
    NODE_OPTIONS="--max-old-space-size=16384" bin/turbo --filter=@posthog/plugin-server prepare
```
**第 113-116 行**: 重新安装，只保留生产依赖
- `--prod`: 只安装 dependencies，不安装 devDependencies
- 这个 node_modules 会被复制到最终镜像
- 减小最终镜像体积

---

## 阶段 3: posthog-build - Django 应用构建

```dockerfile
FROM python:3.12.11-slim-bookworm AS posthog-build
```
**第 122 行**: 基于 Python 3.12.11（与 pyproject.toml 版本一致）
- `slim`: 精简版本，减小体积

```dockerfile
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
```
**第 123-124 行**: 设置工作目录和严格 shell 模式

### 安装 Python 依赖

```dockerfile
COPY pyproject.toml uv.lock ./
```
**第 129 行**: 复制 Python 依赖配置
- `pyproject.toml`: Python 项目配置（PEP 518）
- `uv.lock`: uv 包管理器的锁文件

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "build-essential" \
    "git" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libffi-dev" \
    "zlib1g-dev" \
    "pkg-config" \
```
**第 130-139 行**: 安装编译 Python 扩展所需的开发库
- `build-essential`: C/C++ 编译工具
- `git`: 某些 pip 包从 git 安装
- `libpq-dev`: PostgreSQL 客户端开发库
- `libxmlsec1*`: XML 安全库（SAML 支持）
- `libffi-dev`: Foreign Function Interface 库
- `zlib1g-dev`: 压缩库
- `pkg-config`: 编译配置工具

```dockerfile
    && \
    rm -rf /var/lib/apt/lists/* && \
    pip install uv~=0.7.0 --no-cache-dir && \
    UV_PROJECT_ENVIRONMENT=/python-runtime uv sync --frozen --no-dev --no-cache --compile-bytecode --no-binary-package lxml --no-binary-package xmlsec
```
**第 141-143 行**: 安装 Python 依赖
- `pip install uv`: 安装 uv 包管理器（比 pip 快很多）
- `UV_PROJECT_ENVIRONMENT=/python-runtime`: 安装到自定义目录
- `uv sync`: 同步依赖
  - `--frozen`: 使用锁文件，不更新
  - `--no-dev`: 不安装开发依赖
  - `--no-cache`: 不使用缓存（避免构建环境问题）
  - `--compile-bytecode`: 预编译为 .pyc（提高启动速度）
  - `--no-binary-package lxml xmlsec`: 从源码编译这两个包（兼容性更好）

```dockerfile
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime
```
**第 145-146 行**: 设置环境变量，使用自定义 Python 环境

### 生成 Django 静态文件

```dockerfile
COPY manage.py manage.py
COPY common/esbuilder common/esbuilder
COPY common/hogvm common/hogvm/
COPY posthog posthog/
COPY products/ products/
COPY ee ee/
```
**第 149-154 行**: 复制 Django 应用代码
- `manage.py`: Django 管理命令
- `posthog/`: 主应用代码
- `ee/`: 企业版代码
- `products/`: 产品功能模块

```dockerfile
COPY --from=frontend-build /code/frontend/dist /code/frontend/dist
```
**第 155 行**: 从 frontend-build 阶段复制前端构建产物
- 多阶段构建的精髓：引用其他阶段的文件

```dockerfile
RUN SKIP_SERVICE_VERSION_REQUIREMENTS=1 STATIC_COLLECTION=1 DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput
```
**第 156 行**: 收集所有静态文件到一个目录
- `SKIP_SERVICE_VERSION_REQUIREMENTS=1`: 跳过服务版本检查（构建时不需要）
- `STATIC_COLLECTION=1`: 标记为静态文件收集模式
- `DATABASE_URL='postgres:///'`: 假数据库 URL（不会真正连接）
- `REDIS_URL='redis:///'`: 假 Redis URL
- `collectstatic --noinput`: 收集静态文件，不询问
- 输出到 `staticfiles/` 目录

---

## 阶段 4: fetch-geoip-db - 下载 GeoIP 数据库

```dockerfile
FROM debian:bookworm-slim AS fetch-geoip-db
```
**第 163 行**: 使用精简的 Debian 基础镜像

```dockerfile
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
```
**第 164-165 行**: 设置工作目录和严格模式

### 下载 GeoIP 数据库

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    "curl" \
    "brotli" \
```
**第 168-172 行**: 安装下载和解压工具
- `ca-certificates`: HTTPS 证书
- `curl`: 下载工具
- `brotli`: Brotli 解压缩工具

```dockerfile
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" --http1.1 | brotli --decompress --output=./share/GeoLite2-City.mmdb ) && \
    chmod -R 755 ./share/GeoLite2-City.mmdb
```
**第 174-177 行**: 下载并解压 GeoLite2 数据库
- `https://mmdbcdn.posthog.net/`: PostHog CDN（托管 MaxMind 的 GeoLite2 数据库）
- `--http1.1`: 强制使用 HTTP/1.1（某些 CDN 兼容性更好）
- `brotli --decompress`: 解压 Brotli 格式
- 输出: `share/GeoLite2-City.mmdb`（城市级别 IP 地理位置数据库）
- 用于将用户 IP 解析为地理位置

---

## 阶段 5: 最终运行时镜像

```dockerfile
FROM unit:1.33.0-python3.12
```
**第 184 行**: 基于 NGINX Unit 1.33.0（Python 3.12 版本）
- NGINX Unit: 动态应用服务器，支持多种语言
- 可在运行时重新配置，无需重启
- 性能优于传统的 Gunicorn + NGINX 组合

```dockerfile
WORKDIR /code
SHELL ["/bin/bash", "-e", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED 1
```
**第 185-187 行**: 设置工作目录、严格 shell、Python 无缓冲输出
- `PYTHONUNBUFFERED=1`: 实时输出日志（不缓冲）

### 安装运行时系统依赖

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "wget" \
    "gnupg" \
```
**第 192-195 行**: 安装基础工具

```dockerfile
    && \
    mkdir -p /etc/apt/keyrings && \
    wget -qO - https://packages.confluent.io/clients/deb/archive.key | gpg --dearmor -o /etc/apt/keyrings/confluent-clients.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/confluent-clients.gpg] https://packages.confluent.io/clients/deb/ bookworm main" > /etc/apt/sources.list.d/confluent-clients.list && \
```
**第 197-199 行**: 添加 Confluent APT 仓库（同构建阶段）

```dockerfile
    apt-get update && \
    apt-get install -y --no-install-recommends \
    "chromium" \
    "chromium-driver" \
    "libpq-dev" \
    "libxmlsec1" \
    "libxmlsec1-dev" \
    "libxml2" \
    "gettext-base" \
    "ffmpeg=7:5.1.7-0+deb12u1" \
    "librdkafka1=2.10.1-1.cflt~deb12" \
    "librdkafka++1=2.10.1-1.cflt~deb12" \
    "libssl-dev=3.0.17-1~deb12u2" \
    "libssl3=3.0.17-1~deb12u2" \
```
**第 200-213 行**: 安装运行时依赖
- `chromium` + `chromium-driver`: 无头浏览器（截图、PDF 导出、会话录制）
- `libpq-dev`: PostgreSQL 客户端库
- `libxmlsec1*`, `libxml2`: XML/SAML 支持
- `gettext-base`: 国际化支持（envsubst 命令）
- `ffmpeg`: 视频处理（会话录制视频导出）
- `librdkafka*`: Kafka 客户端库（运行时版本，不需要 dev）
- `libssl*`: OpenSSL 库

```dockerfile
    && \
    rm -rf /var/lib/apt/lists/*
```
**第 215 行**: 清理 apt 缓存

### 安装 MS SQL Server 驱动

```dockerfile
RUN curl https://packages.microsoft.com/keys/microsoft.asc | tee /etc/apt/trusted.gpg.d/microsoft.asc && \
    curl https://packages.microsoft.com/config/debian/11/prod.list | tee /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*
```
**第 218-222 行**: 安装 Microsoft ODBC Driver for SQL Server
- 支持连接 MS SQL Server 数据仓库
- `ACCEPT_EULA=Y`: 自动接受许可协议
- `msodbcsql18`: ODBC Driver 18 for SQL Server

### 安装 Node.js

```dockerfile
ENV NODE_VERSION 22.17.1
```
**第 225 行**: 定义 Node.js 版本

```dockerfile
RUN ARCH= && dpkgArch="$(dpkg --print-architecture)" \
  && case "${dpkgArch##*-}" in \
    amd64) ARCH='x64';; \
    ppc64el) ARCH='ppc64le';; \
    s390x) ARCH='s390x';; \
    arm64) ARCH='arm64';; \
    armhf) ARCH='armv7l';; \
    i386) ARCH='x86';; \
    *) echo "unsupported architecture"; exit 1 ;; \
  esac \
```
**第 227-236 行**: 架构检测
- 检测系统架构（x86_64, ARM64 等）
- 映射到 Node.js 的架构命名
- 支持多架构构建

```dockerfile
  && export GNUPGHOME="$(mktemp -d)" \
  && set -ex \
  && for key in \
    5BE8A3F6C8A5C01D106C0AD820B1A390B168D356 \
    C0D6248439F1D5604AAFFB4021D900FFDB233756 \
    DD792F5973C6DE52C432CBDAC77ABFA00DDBF2B7 \
    CC68F5A3106FF448322E48ED27F5E38D5B0A215F \
    8FCCA13FEF1D0C2E91008E09770F7A9A5AE15600 \
    890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4 \
    C82FA3AE1CBEDC6BE46B9360C43CEC45C17AB93C \
    108F52B48DB57BB0CC439B2997B01419BD92F80A \
    A363A499291CBBC940DD62E41F10027AF002F8B0 \
  ; do \
      { gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys "$key" && gpg --batch --fingerprint "$key"; } || \
      { gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key" && gpg --batch --fingerprint "$key"; } ; \
  done \
```
**第 237-252 行**: 导入 Node.js 官方 GPG 密钥
- 9 个 Node.js 发布者的 GPG 密钥指纹
- 从两个密钥服务器尝试下载（容错机制）
- 用于验证下载文件的真实性

```dockerfile
  && curl -fsSLO --compressed "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$ARCH.tar.xz" \
  && curl -fsSLO --compressed "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt.asc" \
  && gpg --batch --decrypt --output SHASUMS256.txt SHASUMS256.txt.asc \
  && gpgconf --kill all \
  && rm -rf "$GNUPGHOME" \
```
**第 253-257 行**: 下载 Node.js 并验证签名
- 下载 Node.js 二进制包（tar.xz 格式）
- 下载 SHA256 校验和文件（GPG 签名版）
- 解密签名文件获取校验和
- 清理 GPG 临时目录

```dockerfile
  && grep " node-v$NODE_VERSION-linux-$ARCH.tar.xz\$" SHASUMS256.txt | sha256sum -c - \
  && tar -xJf "node-v$NODE_VERSION-linux-$ARCH.tar.xz" -C /usr/local --strip-components=1 --no-same-owner \
  && rm "node-v$NODE_VERSION-linux-$ARCH.tar.xz" SHASUMS256.txt.asc SHASUMS256.txt \
  && ln -s /usr/local/bin/node /usr/local/bin/nodejs \
  && node --version \
  && npm --version \
  && rm -rf /tmp/*
```
**第 258-264 行**: 验证、安装、清理
- `sha256sum -c`: 验证下载文件的校验和
- `tar -xJf`: 解压到 `/usr/local`
- `--strip-components=1`: 去掉顶层目录
- `ln -s`: 创建 nodejs 符号链接（兼容性）
- 验证安装成功
- 清理下载文件

### 创建非 root 用户

```dockerfile
RUN groupadd -g 1000 posthog && \
    useradd -r -g posthog posthog && \
    chown posthog:posthog /code
USER posthog
```
**第 267-270 行**: 安全最佳实践
- 创建 `posthog` 组（GID 1000）
- 创建 `posthog` 用户（系统用户）
- 设置 `/code` 目录权限
- 切换到非 root 用户（提高安全性）

### 添加构建信息

```dockerfile
ARG COMMIT_HASH
RUN echo $COMMIT_HASH > /code/commit.txt
```
**第 273-274 行**: 记录构建的 Git commit hash
- 用于版本追踪和诊断
- 在运行时可通过 `/_health` 端点查看

### 复制 Plugin Server 构建产物

```dockerfile
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/dist /code/rust/cyclotron-node/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/package.json /code/rust/cyclotron-node/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/rust/cyclotron-node/index.node /code/rust/cyclotron-node/index.node
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/dist /code/common/plugin_transpiler/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/node_modules /code/common/plugin_transpiler/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/plugin_transpiler/package.json /code/common/plugin_transpiler/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/hogvm/typescript/dist /code/common/hogvm/typescript/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/common/hogvm/typescript/node_modules /code/common/hogvm/typescript/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/dist /code/plugin-server/dist
COPY --from=plugin-server-build --chown=posthog:posthog /code/node_modules /code/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/node_modules /code/plugin-server/node_modules
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/package.json /code/plugin-server/package.json
COPY --from=plugin-server-build --chown=posthog:posthog /code/plugin-server/assets /code/plugin-server/assets
```
**第 277-289 行**: 从 plugin-server-build 阶段复制编译后的代码
- `--chown=posthog:posthog`: 设置正确的文件所有权
- 复制内容：
  - cyclotron（Rust + Node.js 混合模块）
  - plugin_transpiler（插件转译器）
  - hogvm（HogQL 虚拟机）
  - plugin-server（编译后的 JS 和生产依赖）
  - node_modules（只有生产依赖）

### 复制 Python 环境和静态文件

```dockerfile
COPY --from=posthog-build --chown=posthog:posthog /code/staticfiles /code/staticfiles
COPY --from=posthog-build --chown=posthog:posthog /python-runtime /python-runtime
ENV PATH=/python-runtime/bin:$PATH \
    PYTHONPATH=/python-runtime
```
**第 292-295 行**: 从 posthog-build 阶段复制
- `staticfiles/`: Django 收集的所有静态文件
- `/python-runtime`: 完整的 Python 环境（依赖 + 工具）
- 设置环境变量使用自定义 Python 环境

### 安装 Playwright

```dockerfile
USER root
RUN /python-runtime/bin/python -m playwright install --with-deps chromium
USER posthog
```
**第 298-300 行**: 安装 Playwright Chromium 浏览器
- 临时切换到 root（需要安装系统依赖）
- `playwright install --with-deps chromium`: 安装 Chromium 及其依赖
- 用于自动化浏览器操作（截图、视频导出）
- 切回 posthog 用户

### 验证视频导出依赖

```dockerfile
RUN ffmpeg -version
RUN /python-runtime/bin/python -c "import playwright; print('Playwright package imported successfully')"
RUN /python-runtime/bin/python -c "from playwright.sync_api import sync_playwright; print('Playwright sync API available')"
```
**第 303-305 行**: 验证关键依赖可用
- 验证 ffmpeg 安装成功
- 验证 Playwright 包可导入
- 验证 Playwright 同步 API 可用
- 构建时失败优于运行时失败

### 复制前端和 GeoIP 数据

```dockerfile
COPY --from=frontend-build --chown=posthog:posthog /code/frontend/dist /code/frontend/dist
```
**第 309 行**: 复制前端构建产物
- TODO 注释表明这可能是冗余的（staticfiles 已包含）

```dockerfile
COPY --from=fetch-geoip-db --chown=posthog:posthog /code/share/GeoLite2-City.mmdb /code/share/GeoLite2-City.mmdb
```
**第 312 行**: 复制 GeoIP 数据库
- 用于 IP 地理位置解析

### 复制应用代码

```dockerfile
COPY --chown=posthog:posthog gunicorn.config.py ./
COPY --chown=posthog:posthog ./bin ./bin/
COPY --chown=posthog:posthog manage.py manage.py
COPY --chown=posthog:posthog posthog posthog/
COPY --chown=posthog:posthog ee ee/
COPY --chown=posthog:posthog common/hogvm common/hogvm/
COPY --chown=posthog:posthog dags dags/
COPY --chown=posthog:posthog products products/
```
**第 315-322 行**: 复制所有应用源代码
- `gunicorn.config.py`: Gunicorn 配置（向后兼容）
- `bin/`: 启动脚本和工具
- `manage.py`: Django 管理命令
- `posthog/`: 主应用代码
- `ee/`: 企业版代码
- `common/hogvm/`: HogQL 虚拟机
- `dags/`: Airflow DAGs（数据管道）
- `products/`: 产品功能模块

**为什么最后才复制源代码？**
- 源代码变化最频繁
- 放在最后可以最大化利用前面的缓存层
- 只有代码变化时才重新构建这一层

### 向后兼容

```dockerfile
RUN cp ./bin/docker-server-unit ./bin/docker-server
```
**第 325 行**: 创建向后兼容的启动脚本
- 旧版本使用 `docker-server`
- 新版本使用 `docker-server-unit`（NGINX Unit）
- 复制一份保持兼容

### 设置环境变量

```dockerfile
ENV NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_PATH=/usr/lib/chromium/ \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver \
    BUILD_LIBRDKAFKA=0
```
**第 328-332 行**: 设置运行时环境变量
- `NODE_ENV=production`: Node.js 生产模式
- `CHROME_BIN`: Chromium 可执行文件路径
- `CHROME_PATH`: Chromium 库路径
- `CHROMEDRIVER_BIN`: ChromeDriver 路径
- `BUILD_LIBRDKAFKA=0`: 使用系统 librdkafka

### 暴露端口

```dockerfile
EXPOSE 8000
```
**第 335 行**: 暴露 HTTP 端口 8000（主 Web 服务）

```dockerfile
EXPOSE 8001
```
**第 338 行**: 暴露 Prometheus Metrics 端口 8001

### 配置 NGINX Unit

```dockerfile
COPY unit.json.tpl /docker-entrypoint.d/unit.json.tpl
```
**第 339 行**: 复制 NGINX Unit 配置模板
- NGINX Unit 启动时会处理 `/docker-entrypoint.d/` 中的文件
- `.tpl` 表示模板文件，可能包含环境变量替换

### 启动命令

```dockerfile
USER root
CMD ["./bin/docker"]
```
**第 340-341 行**: 设置容器启动命令
- 切换到 root（NGINX Unit 需要 root 启动，之后会降权）
- `./bin/docker`: 启动脚本（处理迁移、启动服务等）

---

## 镜像大小优化技巧

### 1. 多阶段构建
- 构建工具不包含在最终镜像
- 只复制必要的运行时文件

### 2. 精简基础镜像
- 使用 `-slim` 版本（debian-slim, python-slim）
- 减少不必要的系统工具

### 3. 合并 RUN 命令
```dockerfile
RUN apt-get update && \
    apt-get install -y pkg1 pkg2 && \
    rm -rf /var/lib/apt/lists/*
```
- 减少层数
- 及时清理缓存

### 4. 利用 BuildKit 缓存
```dockerfile
RUN --mount=type=cache,id=pnpm,target=/tmp/pnpm-store-v23
```
- 跨构建复用下载的包
- 不增加镜像体积

### 5. 精确版本锁定
```dockerfile
"librdkafka1=2.10.1-1.cflt~deb12"
```
- 确保可重现构建
- 避免意外升级导致的问题

### 6. 延迟复制源代码
- 先安装依赖（变化少）
- 后复制源码（变化多）
- 最大化缓存命中率

---

## 安全最佳实践

### 1. 非 root 用户运行
```dockerfile
USER posthog
```
- 减小攻击面
- 限制容器内权限

### 2. 固定软件版本
```dockerfile
FROM python:3.12.11-slim-bookworm
```
- 避免使用 `latest` 标签
- 确保一致性和安全性

### 3. GPG 签名验证
```dockerfile
gpg --batch --decrypt --output SHASUMS256.txt SHASUMS256.txt.asc
```
- 验证下载文件的真实性
- 防止供应链攻击

### 4. 及时清理临时文件
```dockerfile
rm -rf /var/lib/apt/lists/*
```
- 减小镜像体积
- 移除敏感信息

### 5. 使用官方源
- Confluent（librdkafka）
- Microsoft（ODBC Driver）
- Node.js 官方
- 避免不可信的第三方源

---

## 构建命令

### 本地构建
```bash
docker build -t posthog/posthog:local .
```

### 多架构构建
```bash
docker buildx build --platform linux/amd64,linux/arm64 -t posthog/posthog:latest .
```

### 传递构建参数
```bash
docker build --build-arg COMMIT_HASH=$(git rev-parse HEAD) -t posthog/posthog:local .
```

### 使用 BuildKit
```bash
DOCKER_BUILDKIT=1 docker build -t posthog/posthog:local .
```

---

## 总结

这个 Dockerfile 是一个生产级别的多阶段构建配置，体现了：

1. **清晰的分层结构**: 前端、后端、依赖各自独立构建
2. **高效的缓存策略**: 依赖安装和源代码构建分离
3. **安全性考虑**: 非 root 用户、签名验证、固定版本
4. **体积优化**: 只保留运行时必需的文件
5. **可维护性**: 清晰的注释和逻辑分组
6. **跨平台支持**: 多架构构建支持

最终镜像包含：
- Python 3.12 + Django 应用
- Node.js 22 + Plugin Server
- NGINX Unit 应用服务器
- Chromium + Playwright（浏览器自动化）
- FFmpeg（视频处理）
- GeoIP 数据库（地理位置）
- 所有必需的系统库

镜像大小约 2-3 GB，包含了完整的 PostHog 功能栈。

