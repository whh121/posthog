# PostHog Deploy-Hobby 脚本逐行解读

本文档对 `bin/deploy-hobby` 脚本进行逐行解析，帮助理解 PostHog Hobby 部署的完整流程。

---

## 脚本头部与基础配置

```bash
#!/usr/bin/env bash
```
**第1行**: Shebang，指定使用 bash 解释器执行此脚本。

```bash
set -e
```
**第3行**: 错误即退出。任何命令返回非零状态码时脚本立即终止，确保安装过程的安全性。

```bash
export DEBIAN_FRONTEND=noninteractive
```
**第5行**: 设置 Debian/Ubuntu 包管理器为非交互模式，apt 安装时不会弹出任何需要用户确认的对话框。

```bash
export RESTART_MODE=l
```
**第8行**: 自动重启模式设置为 `l` (list services)，用于 `needrestart` 命令，避免安装过程中需要用户手动选择是否重启服务。

```bash
export POSTHOG_APP_TAG="${POSTHOG_APP_TAG:-latest}"
```
**第9行**: 设置 PostHog 应用版本标签，如果环境变量 `POSTHOG_APP_TAG` 已存在则使用它，否则默认为 `latest`。

---

## 密钥生成

```bash
POSTHOG_SECRET=$(head -c 28 /dev/urandom | sha224sum -b | head -c 56)
export POSTHOG_SECRET
```
**第11-12行**: 生成 PostHog 密钥：
- `head -c 28 /dev/urandom`: 从随机数生成器读取 28 字节
- `sha224sum -b`: 计算 SHA-224 哈希值（二进制模式）
- `head -c 56`: 取前 56 个字符
- 最终得到一个 56 字符的随机密钥，用于 Django SECRET_KEY

```bash
ENCRYPTION_SALT_KEYS=$(openssl rand -hex 16)
export ENCRYPTION_SALT_KEYS
```
**第14-15行**: 生成加密盐值密钥：
- `openssl rand -hex 16`: 使用 OpenSSL 生成 16 字节的十六进制随机字符串（32 个字符）
- 用于数据加密和解密

---

## 用户交互提示

```bash
echo "Welcome to the single instance PostHog installer 🦔"
echo ""
echo "⚠️  You really need 4gb or more of memory to run this stack ⚠️"
echo ""
echo "Power user or aspiring power user?"
echo "Check out our docs on deploying PostHog! https://posthog.com/docs/self-host/deploy/hobby"
echo ""
```
**第18-24行**: 欢迎信息和资源要求提示，告知用户需要至少 4GB 内存，并提供文档链接。

---

## 版本选择逻辑

```bash
if [ -n "$1" ]
then
export POSTHOG_APP_TAG=$1
```
**第26-28行**: 如果提供了第一个参数（`$1` 非空），直接使用它作为版本标签。

```bash
else
echo "What version of PostHog would you like to install? (We default to 'latest')"
echo "You can check out available versions here: https://hub.docker.com/r/posthog/posthog/tags"
read -r POSTHOG_APP_TAG_READ
```
**第29-32行**: 否则询问用户想要安装的版本，从标准输入读取。

```bash
if [ -z "$POSTHOG_APP_TAG_READ" ]
then
    echo "Using default and installing $POSTHOG_APP_TAG"
else
    export POSTHOG_APP_TAG=$POSTHOG_APP_TAG_READ
    echo "Using provided tag: $POSTHOG_APP_TAG"
fi
```
**第33-39行**: 如果用户直接回车（输入为空），使用默认的 `latest`；否则使用用户输入的版本。

---

## 域名配置

```bash
if [ -n "$2" ]
then
export DOMAIN=$2
```
**第42-44行**: 如果提供了第二个参数，直接使用它作为域名。

```bash
else
echo "Let's get the exact domain PostHog will be installed on"
echo "Make sure that you have a Host A DNS record pointing to this instance!"
echo "This will be used for TLS 🔐"
echo "ie: test.posthog.net (NOT an IP address)"
read -r DOMAIN
export DOMAIN=$DOMAIN
fi
```
**第45-52行**: 否则询问用户域名，强调需要配置 DNS A 记录，域名将用于 TLS 证书申请。

```bash
echo "Ok we'll set up certs for https://$DOMAIN"
```
**第53行**: 确认将为该域名设置 HTTPS 证书。

---

## 获取 sudo 权限

```bash
echo "We will need sudo access so the next question is for you to give us superuser access"
echo "Please enter your sudo password now:"
sudo echo ""
echo "Thanks! 🙏"
```
**第55-58行**: 
- 提示用户需要 sudo 权限
- 执行 `sudo echo ""` 触发密码输入（密码会被缓存一段时间）
- 感谢用户授权

---

## 停止现有服务

```bash
echo "Making sure any stack that might exist is stopped"
sudo -E docker-compose -f docker-compose.yml stop &> /dev/null || true
```
**第62-63行**: 
- 尝试停止可能存在的旧服务
- `-E`: 保留当前环境变量
- `&> /dev/null`: 重定向所有输出到黑洞
- `|| true`: 即使失败也不终止脚本（因为可能不存在旧服务）

---

## 安装分析追踪

```bash
curl -o /dev/null -L --header "Content-Type: application/json" -d "{
    \"api_key\": \"sTMFPsFhdP1Ssg\",
    \"distinct_id\": \"${DOMAIN}\",
    \"properties\": {\"domain\": \"${DOMAIN}\"},
    \"type\": \"capture\",
    \"event\": \"magic_curl_install_start\"
}" https://us.i.posthog.com/batch/ &> /dev/null
```
**第66-72行**: 发送匿名事件到 PostHog 云端，追踪安装开始，用于统计和改进安装体验。使用域名作为唯一标识。

---

## 系统准备

```bash
echo "Grabbing latest apt caches"
sudo apt update
```
**第75-76行**: 更新 apt 包索引，确保能安装最新版本的软件包。

---

## 克隆代码仓库

```bash
echo "Installing PostHog 🦔 from Github"
sudo apt install -y git
```
**第79-80行**: 安装 Git（`-y` 自动确认）。

```bash
git clone https://github.com/PostHog/posthog.git &> /dev/null || true
cd posthog
```
**第82-83行**: 
- 克隆 PostHog 仓库（如果目录已存在则跳过，`|| true` 防止报错）
- 进入 posthog 目录

---

## 版本切换逻辑

### latest-release 分支

```bash
if [[ "$POSTHOG_APP_TAG" = "latest-release" ]]
then
    git fetch --tags
    latestReleaseTag=$(git describe --tags "$(git rev-list --tags --max-count=1)")
    echo "Checking out latest PostHog release: $latestReleaseTag"
    echo "Warning PostHog don't create tagged releases anymore. It's way better to use 'latest' than 'latest-release'"
    git checkout "$latestReleaseTag"
```
**第85-91行**: 
- 如果选择 `latest-release`
- 获取所有标签
- 找到最新的 tag：`git rev-list --tags --max-count=1` 获取最新 tag 的 commit，然后用 `git describe --tags` 获取 tag 名
- 警告：PostHog 已不再创建 tagged releases
- 切换到该标签

### latest 分支

```bash
elif [[ "$POSTHOG_APP_TAG" = "latest" ]]
then
    echo "Fetching latest changes from origin"
    git fetch origin
    current_branch=$(git branch --show-current)
    if [ -n "$current_branch" ]; then
        echo "Updating branch '$current_branch' to latest from origin"
        git reset --hard "origin/$current_branch"
    else
        echo "On detached HEAD: $(git rev-parse --short HEAD)"
    fi
    echo "Now on commit: $(git rev-parse --short HEAD)"
```
**第92-103行**: 
- 如果选择 `latest`
- 拉取最新更改
- 获取当前分支名
- 如果在某个分支上，强制重置到远程分支最新状态（`git reset --hard`）
- 如果在 detached HEAD 状态，仅显示当前 commit
- 最后显示当前所在 commit 的短哈希

### 特定 commit hash

```bash
elif [[ "$POSTHOG_APP_TAG" =~ ^[0-9a-f]{40}$ ]]
then
    echo "Checking out specific commit hash: $POSTHOG_APP_TAG"
    git checkout "$POSTHOG_APP_TAG"
```
**第104-107行**: 
- 正则匹配 40 位十六进制字符（完整的 Git commit hash）
- 直接 checkout 到该 commit

### 特定 release tag

```bash
else
    releaseTag="${POSTHOG_APP_TAG/release-/""}"
    git fetch --tags
    echo "Checking out PostHog release: $releaseTag"
    git checkout "$releaseTag"
fi
```
**第108-113行**: 
- 其他情况视为 release tag
- 移除 `release-` 前缀（如果有）
- 拉取所有 tags
- checkout 到指定 tag

```bash
cd ..
```
**第115行**: 返回上一级目录。

---

## TLS 配置

```bash
if [ -n "$3" ]
then
export TLS_BLOCK="acme_ca https://acme-staging-v02.api.letsencrypt.org/directory"
fi
```
**第117-120行**: 如果提供了第三个参数，使用 Let's Encrypt 的 staging 环境（用于测试，避免触发速率限制）。

```bash
if [ "$REGISTRY_URL" == "" ]
then
export REGISTRY_URL="posthog/posthog"
fi
```
**第122-125行**: 如果未设置 Docker 镜像仓库地址，默认使用 Docker Hub 的 `posthog/posthog`。

---

## 生成环境配置文件

```bash
cat > .env <<EOF
POSTHOG_SECRET=$POSTHOG_SECRET
ENCRYPTION_SALT_KEYS=$ENCRYPTION_SALT_KEYS
DOMAIN=$DOMAIN
TLS_BLOCK=$TLS_BLOCK
REGISTRY_URL=$REGISTRY_URL
CADDY_TLS_BLOCK=$TLS_BLOCK
CADDY_HOST="$DOMAIN, http://, https://"
POSTHOG_APP_TAG=$POSTHOG_APP_TAG
SESSION_RECORDING_V2_METADATA_SWITCHOVER=$(date -Iseconds)
EOF
```
**第130-140行**: 创建 `.env` 文件，包含：
- PostHog 密钥和加密盐值
- 域名配置
- TLS 相关配置
- Caddy 反向代理配置（支持 http 和 https）
- Docker 镜像版本
- 会话录制 v2 元数据切换时间戳（ISO 8601 格式）

---

## 下载 GeoIP 数据库

```bash
echo "Downloading GeoIP database file"
apt-get update &&
apt-get install -y --no-install-recommends curl ca-certificates brotli &&
mkdir -p ./share &&
```
**第143-146行**: 
- 更新包索引
- 安装必要工具：curl（下载）、ca-certificates（HTTPS）、brotli（解压缩）
- `--no-install-recommends`: 不安装推荐的包，节省空间
- 创建共享目录

```bash
if [ ! -f ./share/GeoLite2-City.mmdb ]; then
    curl -L 'https://mmdbcdn.posthog.net/' --http1.1 | brotli --decompress --output=./share/GeoLite2-City.mmdb &&
    echo '{\"date\": \"'"$(date +%Y-%m-%d)"'\"}' > ./share/GeoLite2-City.json;
    chmod 644 ./share/GeoLite2-City.mmdb &&
    chmod 644 ./share/GeoLite2-City.json
fi
```
**第147-152行**: 
- 检查 GeoLite2 数据库是否已存在
- 如果不存在：
  - 下载 brotli 压缩的数据库文件并解压（`--http1.1` 强制使用 HTTP/1.1）
  - 创建包含下载日期的 JSON 元数据文件
  - 设置文件权限为 644（所有者读写，其他人只读）

---

## 创建启动脚本

```bash
rm -rf compose
mkdir -p compose
```
**第157-158行**: 删除旧的 compose 目录，创建新的。

### 主启动脚本

```bash
cat > compose/start <<EOF
#!/bin/bash
./compose/wait
./bin/migrate
./bin/docker-server
EOF
chmod +x compose/start
```
**第159-165行**: 创建主启动脚本：
1. 等待依赖服务就绪（ClickHouse、Postgres）
2. 运行数据库迁移
3. 启动 Django 服务器
4. 添加可执行权限

### Temporal Worker 脚本

```bash
cat > compose/temporal-django-worker <<EOF
#!/bin/bash
./bin/temporal-django-worker
EOF
chmod +x compose/temporal-django-worker
```
**第167-171行**: 创建 Temporal Django Worker 启动脚本（用于异步任务处理）。

### 等待脚本

```bash
cat > compose/wait <<EOF
#!/usr/bin/env python3

import socket
import time

def loop():
    print("Waiting for ClickHouse and Postgres to be ready")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('clickhouse', 9000))
        print("Clickhouse is ready")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('db', 5432))
        print("Postgres is ready")
    except ConnectionRefusedError as e:
        time.sleep(5)
        loop()

loop()
EOF
chmod +x compose/wait
```
**第174-195行**: 创建 Python 等待脚本：
- 使用 socket 连接测试服务是否就绪
- ClickHouse: 端口 9000
- Postgres: 端口 5432
- 如果连接失败，等待 5 秒后递归重试
- 确保依赖服务启动后再启动主应用

---

## Docker 安装

```bash
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Setting up Docker."
```
**第200-201行**: 检查 Docker 是否已安装（`command -v` 检查命令是否存在）。

```bash
    sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
```
**第204行**: 安装 Docker 仓库所需的依赖：
- `apt-transport-https`: 支持 HTTPS 源
- `ca-certificates`: SSL 证书
- `curl`: 下载工具
- `software-properties-common`: 管理软件源

```bash
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo -E apt-key add -
```
**第205行**: 下载并添加 Docker 官方 GPG 密钥（验证包的真实性）。

```bash
    sudo add-apt-repository -y "deb [arch=amd64] https://download.docker.com/linux/ubuntu jammy stable"
```
**第206行**: 添加 Docker 的 Ubuntu Jammy (22.04) stable 版本仓库。

```bash
    sudo apt update
    sudo apt-cache policy docker-ce
    sudo apt install -y docker-ce
```
**第207-209行**: 
- 更新包索引
- 显示 docker-ce 的可用版本（可选，用于确认）
- 安装 Docker CE (Community Edition)

```bash
else
    echo "Docker is already installed. Skipping installation."
fi
```
**第210-212行**: 如果 Docker 已安装，跳过安装步骤。

---

## Docker Compose 安装

```bash
echo "Setting up Docker Compose"
sudo curl -L "https://github.com/docker/compose/releases/download/v2.33.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose || true
sudo chmod +x /usr/local/bin/docker-compose
```
**第215-217行**: 
- 下载 Docker Compose v2.33.1
- `$(uname -s)`: 系统名（Linux）
- `$(uname -m)`: 架构（x86_64/aarch64 等）
- 安装到 `/usr/local/bin/docker-compose`
- 添加可执行权限
- `|| true`: 即使下载失败也继续（可能已安装）

---

## Docker 用户权限

```bash
sudo usermod -aG docker "${USER}" || true
```
**第220行**: 将当前用户添加到 docker 组，允许无需 sudo 运行 docker 命令（需要重新登录生效）。

---

## 启动服务

```bash
echo "Configuring Docker Compose...."
rm -f docker-compose.yml
cp posthog/docker-compose.base.yml docker-compose.base.yml
cp posthog/docker-compose.hobby.yml docker-compose.yml
```
**第223-226行**: 
- 删除旧的 docker-compose.yml
- 复制基础配置文件
- 复制 hobby 部署配置文件

```bash
echo "Starting the stack!"
sudo -E docker-compose -f docker-compose.yml up -d --no-build --pull always
```
**第227-228行**: 启动所有服务：
- `-E`: 保留环境变量（包括 `.env` 中的变量）
- `up -d`: 后台启动
- `--no-build`: 不构建镜像（直接使用预构建的）
- `--pull always`: 总是拉取最新镜像

---

## 健康检查

```bash
echo "We will need to wait ~5-10 minutes for things to settle down, migrations to finish, and TLS certs to be issued"
echo ""
echo "⏳ Waiting for PostHog web to boot (this will take a few minutes)"
```
**第230-232行**: 提示用户需要等待服务启动、迁移完成、TLS 证书签发。

```bash
if bash -c 'while [[ "$(curl -s -o /dev/null -w ''%{http_code}'' localhost/_health)" != "200" ]]; do sleep 5; done'; then
```
**第233行**: 循环检查健康端点：
- `curl -s -o /dev/null -w '%{http_code}'`: 静默请求，只输出 HTTP 状态码
- `localhost/_health`: PostHog 健康检查端点
- 每 5 秒检查一次，直到返回 200

```bash
    echo "⌛️ PostHog looks up!"
    echo ""
    echo "🎉🎉🎉  Done! 🎉🎉🎉"
```
**第234-236行**: 成功启动提示。

```bash
    curl -o /dev/null -L --header "Content-Type: application/json" -d "{
        \"api_key\": \"sTMFPsFhdP1Ssg\",
        \"distinct_id\": \"${DOMAIN}\",
        \"properties\": {\"domain\": \"${DOMAIN}\"},
        \"type\": \"capture\",
        \"event\": \"magic_curl_install_complete\"
    }" https://us.i.posthog.com/batch/ &> /dev/null
```
**第238-244行**: 发送安装完成事件到 PostHog 云端。

```bash
else
    echo "Failed to detect PostHog web boot. Please check the logs with 'docker-compose logs' for more details."
fi
```
**第245-247行**: 如果健康检查失败，提示用户查看日志。

---

## 使用说明

```bash
echo ""
echo "To stop the stack run 'docker-compose stop'"
echo "To start the stack again run 'docker-compose start'"
echo "If you have any issues at all delete everything in this directory and run the curl command again"
echo ""
```
**第249-253行**: 提供基本的操作命令。

```bash
echo 'To upgrade: run /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/upgrade-hobby)"'
```
**第255行**: 提供升级命令（shellcheck disable 注释说明不要展开单引号内的变量）。

```bash
echo ""
echo "PostHog will be up at the location you provided!"
echo "https://${DOMAIN}"
echo ""
echo "It's dangerous to go alone! Take this: 🦔"
```
**第257-261行**: 最终提示和访问地址，以及一个可爱的刺猬表情（PostHog 的吉祥物）。

---

## 总体流程概览

1. **初始化**: 设置环境变量、生成密钥
2. **用户输入**: 收集版本、域名等配置信息
3. **权限获取**: 获取 sudo 权限
4. **代码准备**: 克隆仓库并切换到指定版本
5. **配置生成**: 创建 .env 文件和启动脚本
6. **依赖安装**: 安装 Docker、Docker Compose、GeoIP 数据库
7. **服务启动**: 启动所有容器服务
8. **健康检查**: 等待服务就绪
9. **完成提示**: 显示访问地址和操作说明

这个脚本实现了 PostHog 的一键部署，处理了从零到运行的所有步骤，包括错误处理、幂等性保证（重复运行安全）和用户友好的交互。

