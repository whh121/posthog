#!/usr/bin/env bash
curDir=`pwd`
composeDir="../tmp-compose-local"

if [ ! -d $composeDir ]; then
    mkdir -p $composeDir
fi

case $1 in
    build)
        echo "Building PostHog image from local code..."
        docker rmi posthog/posthog:local || true
        docker build -t posthog/posthog:local -f Dockerfile .
        echo "Build complete: posthog/posthog:local"
        ;;
        
    compose)
        echo "Generating docker-compose configuration..."
        
        export REGISTRY_URL="posthog/posthog"
	export POSTHOG_APP_TAG="${POSTHOG_APP_TAG:-local}"
        
	POSTHOG_SECRET=$(head -c 28 /dev/urandom | sha224sum -b | head -c 56)
        export POSTHOG_SECRET

        ENCRYPTION_SALT_KEYS=$(openssl rand -hex 16)
        export ENCRYPTION_SALT_KEYS

        export DOMAIN=p.x.me

	# Let's Encrypt 生产环境有严格的速率限制：
	# 50 个证书/每个域名/每周
	# 5 次失败验证/每个账户/每小时
	# 测试时使用 staging 环境可以：
	# 避免触发速率限制
	# 安全测试配置
	# 失败了不会影响生产配额 
	# TLS_BLOCK 为空Caddy 使用 Let's Encrypt 生产环境
        # export TLS_BLOCK="acme_ca https://acme-staging-v02.api.letsencrypt.org/directory"
        
	# export DEBIAN_FRONTEND=noninteractive
        # export RESTART_MODE=l
        
	cd $composeDir
	
	# Download GeoLite2-City.mmdb if it doesn't exist
	echo "Downloading GeoIP database file"
	apt-get update &&
	apt-get install -y --no-install-recommends curl ca-certificates brotli &&
	mkdir -p ./share &&
	if [ ! -f ./share/GeoLite2-City.mmdb ]; then
	    curl -L 'https://mmdbcdn.posthog.net/' --http1.1 | brotli --decompress --output=./share/GeoLite2-City.mmdb &&
	    echo '{\"date\": \"'"$(date +%Y-%m-%d)"'\"}' > ./share/GeoLite2-City.json;
	    chmod 644 ./share/GeoLite2-City.mmdb &&
	    chmod 644 ./share/GeoLite2-City.json
	fi

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

	rm -rf compose
        mkdir -p compose
        cat > compose/start <<EOF
#!/bin/bash
/compose/wait
./bin/migrate
./bin/docker-server
EOF
        chmod +x compose/start

        cat > compose/temporal-django-worker <<EOF
#!/bin/bash
./bin/temporal-django-worker
EOF
        chmod +x compose/temporal-django-worker
        
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

	echo "Configuring Docker Compose...."
	rm -f docker-compose.yml

        cp $curDir/docker-compose.base.yml docker-compose.base.yml
	cp $curDir/docker-compose.hobby.yml docker-compose.yml
        
	cd $curDir
        echo "Configuration generated in $composeDir"
        ;;
        
    up)
        echo "Starting PostHog services..."
        cd $composeDir && docker-compose -f docker-compose.yml up -d
        echo "Services started. Access PostHog at http://$DOMAIN or http://localhost:8000"
        ;;
        
    down)
        echo "Stopping PostHog services..."
        cd $composeDir && docker-compose -f docker-compose.yml down
        echo "Services stopped"
        ;;
        
    *)
        echo "Usage: $0 {build|compose|up|down}"
        echo ""
        echo "Commands:"
        echo "  build   - Build PostHog Docker image from local code (tag: posthog/posthog:local)"
        echo "  compose - Generate docker-compose configuration files"
        echo "  up      - Start PostHog services"
        echo "  down    - Stop PostHog services"
        echo ""
        echo "Typical workflow:"
        echo "  1. $0 build     # Build from local code"
        echo "  2. $0 compose   # Generate config (set POSTHOG_APP_TAG=local to use local build)"
        echo "  3. $0 up        # Start services"
        echo "  4. $0 down      # Stop services when done"
        exit 1
        ;;
esac

