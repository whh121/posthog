#!/usr/bin/env bash
curDir=`pwd`
composeDir="../tmp-compose"
if [ ! -d $composeDir ]; then
    mkdir -p $composeDir
fi
case $1 in
        compose)
export TLS_BLOCK="acme_ca https://acme-staging-v02.api.letsencrypt.org/directory"
export REGISTRY_URL="posthog/posthog"
export DOMAIN=p.x.me
export DEBIAN_FRONTEND=noninteractive
export RESTART_MODE=l
export POSTHOG_APP_TAG="${POSTHOG_APP_TAG:-latest}"
export SENTRY_DSN="${SENTRY_DSN:-'https://public@sentry.example.com/1'}"

POSTHOG_SECRET=$(head -c 28 /dev/urandom | sha224sum -b | head -c 56)
export POSTHOG_SECRET

ENCRYPTION_SALT_KEYS=$(openssl rand -hex 16)
export ENCRYPTION_SALT_KEYS

cd $composeDir
rm -f Caddyfile
envsubst > Caddyfile <<EOF
$DOMAIN, http://, https:// {
encode gzip zstd
reverse_proxy http://web:8000
tls test@$DOMAIN
}
EOF
envsubst > .env <<EOF
POSTHOG_SECRET=$POSTHOG_SECRET
ENCRYPTION_SALT_KEYS=$ENCRYPTION_SALT_KEYS
SENTRY_DSN=$SENTRY_DSN
DOMAIN=$DOMAIN
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

cp $curDir/docker-compose.base.yml docker-compose.base.yml
envsubst < $curDir/docker-compose.hobby.yml > docker-compose.yml
cd ..
        ;;
        build)
docker rmi posthog/posthog:latest
docker build -t posthog/posthog:latest -f Dockerfile .
                ;;
        start)
cd $composeDir && docker-compose -f docker-compose.yml up -d
                ;;
        down)
cd $composeDir && docker-compose -f docker-compose.yml down
        ;;
        delvol)
docker volume rm $(docker volume ls -q)
        ;;
        prune)
docker system prune
        ;;
        auth)
docker exec -it tmp-compose-db-1 psql -U posthog -c "UPDATE posthog_organization SET \
        available_product_features[0] = '{\"key\": \"advanced_permissions\"}'::jsonb, \
        available_product_features[1] = '{\"key\": \"organizations_projects\"}'::jsonb, \
        available_product_features[2] = '{\"key\": \"project_based_permissioning\"}'::jsonb, \
        available_product_features[3] = '{\"key\": \"ingestion_taxonomy\"}'::jsonb, \
        available_product_features[4] = '{\"key\": \"paths_advanced\"}'::jsonb, \
        available_product_features[5] = '{\"key\": \"correlation_analysis\"}'::jsonb, \
        available_product_features[6] = '{\"key\": \"group_analytics\"}'::jsonb, \
        available_product_features[7] = '{\"key\": \"tagging\"}'::jsonb, \
        available_product_features[8] = '{\"key\": \"behavioral_cohort_filtering\"}'::jsonb, \
        available_product_features[9] = '{\"key\": \"recordings_playlists\"}'::jsonb, \
        available_product_features[10] = '{\"key\": \"role_based_access\"}'::jsonb, \
        available_product_features[11] = '{\"key\": \"recordings_file_export\"}'::jsonb, \
        available_product_features[12] = '{\"key\": \"recordings_performance\"}'::jsonb, \
        available_product_features[13] = '{\"key\": \"white_labelling\"}'::jsonb;"
        ;;
        *)
echo "not support"
        ;;
esac