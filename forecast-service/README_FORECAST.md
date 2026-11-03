# 交易量预测服务 — 环境创建说明

## 环境要求
- Python 3.13.x
- PostgreSQL（复用 NginxPulse 的库，DSN 见 `configs/nginxpulse_config.dev.json`）

## 创建步骤

### 1. 创建虚拟环境（放在 workspace 下，勿放 ~/.workbuddy）
```bash
cd /home/joyce/workspace
python3.13 -m venv .venv-forecast
```
> ⚠️ 不要建在 `~/.workbuddy/` 下——该目录有 7GB 数据且命中 btrfs 配额，pip 安装会报 `No space left on device`。

### 2. 激活并安装依赖（务必设置 TMPDIR）
```bash
export TMPDIR=/home/joyce/workspace/.tmp
mkdir -p "$TMPDIR"
source .venv-forecast/bin/activate
pip install -r nginxpulse/forecast-service/requirements.txt
```
> ⚠️ 本机 `/tmp` 是 **tmpfs 且只有 10MB**，pip 下载/解压临时文件会撑爆报 `No space left on device`。
> 必须把 `TMPDIR` 指向 workspace 下的普通目录（有 140GB+ 可用空间）。

### 3. 验证
```bash
python -c "import fastapi, pandas, numpy, statsmodels, lightgbm, sklearn, psycopg2; print('依赖 OK')"
```

## 启动预测服务
```bash
cd /home/joyce/workspace/nginxpulse/forecast-service
USE_MOCK=true FORECAST_PORT=8090 python -m app.main
```
> 默认 `USE_MOCK=true`，历史时序由 mock 生成器产出，无需真实数据源即可运行/测试/验证。
> 切真实数据时设 `USE_MOCK=false` 并配置 DB_* 环境变量。
