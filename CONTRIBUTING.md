# Contributing

感谢贡献。

## 开发环境

后端：

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

前端：

```bash
cd frontend
pnpm install
```

## 提交前检查

请至少执行：

```bash
./scripts/run-tests.sh
```

如果修改了前端，也请执行：

```bash
./scripts/run-lint.sh
cd src/frontend
pnpm build
```

## 安全要求

请不要提交以下内容：

- `.env`、`.env.*`
- `config.yaml`
- `wrangler.jsonc`
- `.deployment.env`
- `data/` 下的本地数据库、配置、会话文件
- 任何真实 token、cookie、密码、SMTP 凭据、API key

新增配置项时，请同步更新：

- `.env.example`
- `config.yaml.example`
- `README.md`

## Pull Request

- 保持修改范围聚焦
- 说明行为变更和兼容性影响
- 涉及 schema 变更时，补充 Alembic migration 和说明
- 涉及权限、登录、通知链路时，补充回归测试
