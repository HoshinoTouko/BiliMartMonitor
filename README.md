# BiliMartMonitor

一个用于监控 Bilibili 魔力赏市场的全栈项目，包含：

- Python 扫描与通知逻辑
- FastAPI 后端
- Next.js 前端
- 支持 SQLite / Cloudflare D1 双数据库后端

当前版本：`0.9.0`

## 功能概览

- 持续扫描 Bilibili 魔力赏市场并落库
- 提供 Web 管理界面（市场、通知、账号、系统设置）
- 支持 SQLite 本地运行和 Cloudflare D1 远端存储
- 支持 Telegram、邮件、短信通知配置
- 支持 Cloudflare Turnstile 登录保护

## 开源前提

仓库已按开源场景做了基础整理，但仍建议在公开前再做一次本地检查：

- 仅使用 `.env.example` 和 `config.yaml.example` 作为模板
- 不要提交 `.env`、`config.yaml`、`wrangler.jsonc`、`.deployment.env`、数据库文件、会话文件
- 如果你曾在本地使用过真实 Telegram / Cloudflare / SMTP 凭据，请先轮换再公开仓库
- 如需披露安全问题，见 `SECURITY.md`

## Quick Start

### 本地运行

1. 安装 Python 依赖：

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -r src/backend/requirements.txt
```

2. 准备本地配置：

```bash
# 可选：首次启动时如果 `.env` 和 `config.yaml` 都不存在，程序会自动用示例模板生成
cp .env.example .env
cp config.yaml.example config.yaml
```

也可以跳过这一步，直接启动任意 CLI / 后端入口。程序首次读取配置时会自动从 `.env.example` 和 `config.yaml.example` 生成一组默认文件。

3. 根据需要填写 `.env` 或 `config.yaml` 中的配置。

4. 先登录一个可用的 Bilibili Session。没有可用 Session 时，扫描不会启动：

```bash
PYTHONPATH=src ./.venv/bin/python src/bsm-cli/login.py
```

5. 启动测试或服务：

```bash
./scripts/run-tests.sh
```

后端开发启动：

```bash
./scripts/run-backend.sh
```

`run-backend.sh` 会在启动前自动执行：
- `alembic upgrade head`

前端开发启动：

```bash
./scripts/run-frontend.sh
```

首次进入网页后，默认后台用户为 `admin / admin`。系统服务启动后，仍需要至少一个有效的 Bilibili Session，扫描任务才会真正抓取数据。

## 配置说明

数据库连接通常走 `.env` / 环境变量；可变运行配置（扫描条件、Session 策略、登录保护、Telegram 运行参数等）位于项目根目录 `config.yaml`，可参考 `config.yaml.example`。

默认使用本地 SQLite：

```bash
BSM_DB_BACKEND=sqlite
BSM_SQLITE_PATH=./data/scan.db
BSM_SQLITE_TEST_PATH=./data/test_scan.db
```

切换到 Cloudflare D1：

```bash
BSM_DB_BACKEND=cloudflare
BSM_CF_ACCOUNT_ID=YOUR_CF_ACCOUNT_ID
BSM_CF_DATABASE_ID=YOUR_CF_D1_DATABASE_ID
BSM_CF_API_TOKEN=YOUR_CF_API_TOKEN
BSM_CF_TIMEOUT=15
```

`.env.example` 仅保留环境级配置。当前主要包含：

- 数据库后端与 Cloudflare D1 连接
- 会话 cookie 签名密钥（`BSM_SESSION_SECRET`，生产环境必须设置）

`config.yaml.example` 包含可在线调整的运行配置，例如：

- 扫描参数
- Cloudflare Turnstile 登录保护
- Telegram 机器人运行参数
- 邮件 / 短信通知
- 管理员告警接收列表

## 数据库迁移

运行时数据库层只负责按 ORM 模型执行 `create_all()`，不再在应用启动时隐式修改 schema。

对于已有数据库，升级前先执行 Alembic：

```bash
PYTHONPATH=src ./.venv/bin/alembic upgrade head
```

这条命令会：

- 创建当前 ORM 模型对应的表结构
- 为旧版 `access_users` / `bili_sessions` 补齐缺失列
- 将旧版 `user_sessions` 数据迁移到 `bili_sessions`
- 在 SQLite 上修复 `bili_sessions.created_by -> access_users.username` 的外键约束

## 运行配置

可变运行配置从项目根目录 `config.yaml` 读取。

示例：

```yaml
scan_mode: latest
interval: 20
api_request_mode: async
scan_timeout_seconds: 15
category: "2312"
timezone: Asia/Shanghai
bili_session_pick_mode: round_robin
bili_session_cooldown_seconds: 60
```

`BiliSession` 选择策略：

- `round_robin`: 按最久未使用的可用 Session 轮询
- `random`: 从当前可用 Session 中随机选择

## 测试

```bash
./scripts/run-tests.sh
```

测试会强制使用本地测试数据库。

## Lint

```bash
./scripts/run-lint.sh
```

## 前端

前端位于 `src/frontend/`，开发说明见 `src/frontend/README.md`。

## Docker 使用

当前已发布镜像：

```bash
docker pull hoshinotouko/bilimartmonitor:0.9.0
```

### 标准 Docker

构建镜像：

```bash
docker build -t bilimart-monitor .
```

使用本地 `.env` 与 `config.yaml` 启动：

```bash
docker run --rm -it \
  -p 8080:8080 \
  --env-file .env \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  bilimart-monitor
```

也可以直接使用已发布镜像启动：

```bash
docker run --rm -it \
  -p 8080:8080 \
  --env-file .env \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  hoshinotouko/bilimartmonitor:0.9.0
```

说明：

- `./data` 会映射到容器内 `/app/data`，用于持久化 SQLite 数据库和运行配置
- `config.yaml` 会以挂载文件方式提供给容器
- 启动后访问 `http://localhost:8080`
- 容器启动后同样需要先登录一个可用的 Bilibili Session，否则后台扫描不会产出有效结果

### Cloudflare Containers

项目也支持将 FastAPI + Next.js 打包为单镜像部署到 Cloudflare Containers。

- `Dockerfile.CloudFlare`: Cloudflare 构建镜像
- `wrangler.jsonc.sample`: Wrangler 配置模板
- `.deployment.env`: 生产环境变量文件（已忽略，需本地创建）

本地模拟：

```bash
./scripts/run-docker.sh
```

默认会以 `--restart unless-stopped` 启动容器；如需改为 `always`：

```bash
RESTART_POLICY=always ./scripts/run-docker.sh
```

云端发布：

```bash
./scripts/deploy-cf.sh
```

## Cloudflare 部署

项目支持使用 Cloudflare Containers 部署单镜像版本。

1. 准备部署配置：

```bash
cp wrangler.jsonc.sample wrangler.jsonc
cp .env.example .deployment.env
```

2. 在 `.deployment.env` 中填写 Cloudflare D1、`BSM_SESSION_SECRET` 等生产环境变量。

3. 按你的账号信息修改 `wrangler.jsonc`，确认镜像、实例、端口和 D1 绑定配置正确。

4. 执行部署：

```bash
./scripts/deploy-cf.sh
```

部署完成后，首次进入系统仍需要先登录一个可用的 Bilibili Session，然后扫描任务才会正常抓取和通知。

## 文档索引

- `CONTRIBUTING.md`: 开发与提交流程
- `SECURITY.md`: 漏洞披露与密钥处理
- `doc/ARCH.md`: 架构说明
- `doc/RULE.md`: 规则说明
- `doc/CHANGELOG.md`: 变更记录
- `doc/ACCOUNT_ACCESS_CONTROL.md`: 账号与权限设计

## Co-workers

- Codex
- Gemini
- Claude

## 贡献

欢迎提交 Issue 和 PR。提交前请先阅读 `CONTRIBUTING.md`。

## 运行截图

![运行截图](doc/runtime-screenshot.png)

© Touko Hoshino
