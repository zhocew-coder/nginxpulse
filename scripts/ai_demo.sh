#!/bin/bash
# AI 功能演示脚本

set -e

echo "====== NginxPulse AI 功能演示 ======"
echo ""

# 检查配置文件
if [ ! -f "configs/ai_config.json" ]; then
    echo "❌ 配置文件不存在：configs/ai_config.json"
    exit 1
fi

echo "✅ 配置文件检查通过"

# 检查迁移脚本
if [ ! -f "scripts/ai_migrate.sql" ]; then
    echo "❌ 迁移脚本不存在：scripts/ai_migrate.sql"
    exit 1
fi

echo "✅ 迁移脚本检查通过"

# 构建 Docker 镜像
echo ""
echo "🔨 开始构建 Docker 镜像..."
docker compose build --build-arg GOPROXY="https://goproxy.cn,direct"

if [ $? -ne 0 ]; then
    echo "❌ Docker 构建失败"
    exit 1
fi

echo "✅ Docker 构建成功"
echo ""

# 提示用户下一步操作
echo "====== 下一步操作 ======"
echo ""
echo "1. 执行数据库迁移（首次启动前）:"
echo "   docker compose exec nginxpulse psql -U nginxpulse -d nginxpulse -f /app/scripts/ai_migrate.sql"
echo ""
echo "2. 启动服务:"
echo "   docker compose up"
echo ""
echo "3. 测试 AI 接口（启动后）:"
echo "   # 触发异常检测"
echo "   curl -X POST http://localhost:8089/api/ai/anomalies/detect"
echo ""
echo "   # NL2SQL 查询测试"
echo "   curl -X POST http://localhost:8089/api/ai/query \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"question\": \"今天有多少 PV？\"}'"
echo ""
echo "   # 生成日报"
echo "   curl -X POST http://localhost:8089/api/ai/reports/generate \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"type\": \"daily\", \"date\": \"'$(date +%Y-%m-%d)'\"}'"
echo ""
echo "====== 演示脚本完成 ======"
