#!/usr/bin/env bash
set -e

check_and_init() {
    # 1 init env
    if [ "$REGISTRY_URL" == "" ]
    then
        export REGISTRY_URL="posthog/posthog"
    fi

    export POSTHOG_APP_TAG="${POSTHOG_APP_TAG:-latest}"

    echo "Checking for named postgres and clickhouse volumes to avoid data loss when upgrading from < 1.39"
    if docker volume ls | grep -Pzoq 'clickhouse-data\n(.|\n)*postgres-data\n'
    then
        DOCKER_VOLUMES_MISSING=FALSE
        echo "Found postgres and clickhouse volumes, proceeding..."
    else
        DOCKER_VOLUMES_MISSING=TRUE
        echo ""
        echo ""
        echo "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨"
        echo "🚨🚨🚨🚨🚨 WARNING: POTENTIAL DATA LOSS 🚨🚨🚨🚨🚨🚨"
        echo "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨"
        echo ""
        echo ""
        echo "We were unable to find named clickhouse and postgres volumes."
        echo "If you created your PostHog stack PRIOR TO August 12th, 2022 / v1.39.0, the Postgres and Clickhouse containers did NOT have persistent named volumes by default."
        echo "If you choose to upgrade, you 💣 will likely lose data 💣 contained in these anonymous volumes."
        echo ""
        echo "See the discussion here for more information: https://github.com/PostHog/posthog/pull/11256"
        echo ""
        echo "WE STRONGLY RECOMMEND YOU:"
        echo ""
        echo "🛑 Stop this script and do not proceed"
        echo "✅ Back up your entire environment/installation (vm, host, etc.), including all docker containers and volumes:"
        echo "✅ Specifically back up the contents of :"
        echo "  ☑ /var/lib/postgresql/data in the postgres (*_db_1) container"
        echo "  ☑ /var/lib/clickhouse in the clickhouse (*_clickhouse_1) container"
        echo "and be ready to check/recopy the data before you boot PostHog next."
        read -r -p "Do you want to proceed anyway? [y/N] " response
        if [[ "$response" =~ ^([yY][eE][sS]|[yY])+$ ]]
        then
            echo "OK!"
        else
            exit
        fi
    fi

    [[ -f ".env" ]] && export $(cat .env | xargs) || ( echo "No .env file found. Please create it with POSTHOG_SECRET and DOMAIN set." && exit 1)

    # we introduced ENCRYPTION_SALT_KEYS and so if there isn't one, need to add it
    # check for it in the .env file
    if ! grep -q "ENCRYPTION_SALT_KEYS" .env; then
        ENCRYPTION_KEY=$(openssl rand -hex 16)
        echo "ENCRYPTION_SALT_KEYS=$ENCRYPTION_KEY" >> .env
        echo "Added missing ENCRYPTION_SALT_KEYS to .env file"
        source .env
    else
        # Read the existing key
        EXISTING_KEY=$(grep "ENCRYPTION_SALT_KEYS" .env | cut -d '=' -f2)
        
        # Check if the existing key is in the correct format (32 bytes base64url)
        if [[ ! $EXISTING_KEY =~ ^[A-Za-z0-9_-]{32}$ ]]; then
            echo "ENCRYPTION_SALT_KEYS is not in the correct fernet format and will not work"
            echo "🛑 Stop this script and do not proceed"
            echo "remove ENCRYPTION_SALT_KEYS from .env and try again"
            exit 1
        fi
    fi

    export POSTHOG_APP_TAG="${POSTHOG_APP_TAG:-latest-release}"

    curDir=`pwd`

    cd $composeDir

    rm -f docker-compose.yml
    cp ${curDir}/docker-compose.base.yml docker-compose.base.yml
    cp ${curDir}/docker-compose-dev.yml docker-compose.yml.tmpl
    envsubst < docker-compose.yml.tmpl > docker-compose.yml
    rm docker-compose.yml.tmpl

    # rewrite entrypoint
    # TODO: this is duplicated from bin/deploy-hobby. We should refactor this into a
    # single script.
    cat > compose/start <<EOF
#!/bin/bash
/compose/wait
./bin/migrate
./bin/docker-server
EOF

    if [ ${DOCKER_VOLUMES_MISSING} == 'TRUE' ];
    then
        echo ""
        echo ""
        echo "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨"
        echo "🚨🚨🚨🚨🚨WARNING: LAST CHANCE TO AVOID DATA LOSS 🚨🚨🚨🚨🚨🚨"
        echo "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨"
        echo ""
        echo ""
        echo "Before we restart the stack, you should restore data you have backed up from the previous warning."
        echo ""
        echo ""
    fi
}

# 构建镜像
build_images() {
    if [ -z "$SERVICE" ]; then
        echo "🔨 构建所有本地镜像，标签: $POSTHOG_APP_TAG..."
        docker compose -f ${composeDir}/docker-compose.yml build
    else
        echo "🔨 构建服务 $SERVICE，标签: $POSTHOG_APP_TAG..."
        docker compose -f ${composeDir}/docker-compose.yml build $SERVICE
    fi
}

# 启动服务
start_services() {
    if [ -z "$SERVICE" ]; then
        echo "🚀 启动所有服务，使用镜像标签: $POSTHOG_APP_TAG..."
        docker compose -f ${composeDir}/docker-compose.yml up -d
    else
        echo "🚀 启动服务 $SERVICE，使用镜像标签: $POSTHOG_APP_TAG..."
        docker compose -f ${composeDir}/docker-compose.yml up -d $SERVICE
    fi
    
    echo "✅ 服务启动完成！"
    if [ -z "$SERVICE" ] || [ "$SERVICE" = "web" ]; then
        echo "  PostHog 应用将在 http://localhost 可用"
    fi
    if [ -z "$SERVICE" ] || [ "$SERVICE" = "objectstorage" ]; then
        echo "  Object Storage 控制台在 http://localhost:19001 可用"
    fi
    echo "  可以通过以下命令查看日志:"
    echo "  $0 logs"
}

# 停止服务
stop_services() {
    if [ -z "$SERVICE" ]; then
        echo "🛑 停止所有服务..."
        docker compose -f ${composeDir}/docker-compose.yml down
    else
        echo "🛑 停止服务 $SERVICE..."
        docker compose -f ${composeDir}/docker-compose.yml stop $SERVICE
    fi
}

# 查看日志
view_logs() {
    if [ -z "$SERVICE" ]; then
        echo "📋 查看所有服务日志..."
        docker compose -f ${composeDir}/docker-compose.yml logs -f
    else
        echo "📋 查看服务 $SERVICE 日志..."
        docker compose -f ${composeDir}/docker-compose.yml logs -f $SERVICE
    fi
}

# 解析参数
parse_args() {
    COMMAND=${1:-"up"}
    shift 2>/dev/null || true
    
    # 默认值
    TAG=""
    SERVICE=""
    
    # 解析参数
    for arg in "$@"; do
        case $arg in
            --tag=*)
            TAG="${arg#*=}"
            ;;
            -srv=*)
            SERVICE="${arg#*=}"
            ;;
            *)
            echo "未知参数: $arg"
            display_usage
            exit 1
            ;;
        esac
    done
    
    # 设置镜像标签
    if [ ! -z "$TAG" ]; then
        export POSTHOG_APP_TAG="$TAG"
        echo "使用指定的镜像标签: $POSTHOG_APP_TAG"
    elif [ ! -z "$POSTHOG_APP_TAG" ]; then
        echo "使用环境变量镜像标签: $POSTHOG_APP_TAG"
    else
        export POSTHOG_APP_TAG="latest"
        echo "使用默认镜像标签: latest"
    fi
    
    # 设置镜像仓库地址
    # 默认使用本地仓库 posthog/posthog
    # ecr仓库: 145023116201.dkr.ecr.ap-southeast-1.amazonaws.com/bigdata
    if [ ! -z "$REGISTRY_URL" ]; then
        echo "使用自定义镜像仓库: $REGISTRY_URL"
    else
        export REGISTRY_URL="posthog/posthog"
        echo "使用本地镜像仓库: $REGISTRY_URL"
    fi
}

# 主程序
main() {
    export DEBIAN_FRONTEND=noninteractive
    composeDir="${HOME}/deploy-compose"

    parse_args "$@"
    setup_env
    check_files
    
    case $COMMAND in
        "init")
            check_and_init
            ;;
        "build")
            build_images
            ;;
        "up")
            build_images
            start_services
            ;;
        "down")
            stop_services
            ;;
        "logs")
            view_logs
            ;;
        "help")
            display_usage
            ;;
        *)
            echo "❌ 未知命令: $COMMAND"
            display_usage
            exit 1
            ;;
    esac
}

# 执行主程序
main "$@" 