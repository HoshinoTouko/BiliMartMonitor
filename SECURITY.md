# Security Policy

## 报告方式

如果你发现安全问题，请不要公开提交包含漏洞细节或敏感数据的 Issue。

建议通过私下渠道联系维护者，并至少提供：

- 问题描述
- 影响范围
- 复现步骤
- 是否已经接触到真实用户数据或凭据

## 凭据处理

本项目不接受以下内容进入版本库：

- Telegram bot token
- Cloudflare API token / Turnstile secret
- 邮箱 SMTP 密码
- 用户 cookie / session
- 生产数据库导出

请使用以下模板文件进行本地配置：

- `.env.example`
- `config.yaml.example`
- `wrangler.jsonc.sample`

## 公开仓库前建议

如果仓库曾经保存过真实凭据，请在公开前完成：

1. 轮换所有已暴露的 token、密码、密钥。
2. 检查 Git 历史，而不只是当前工作区。
3. 清理部署平台上的旧环境变量和测试账号。
4. 确认示例配置文件中只包含占位符。

## 范围说明

当前仓库主要风险面包括：

- 登录鉴权
- Telegram / 邮件通知
- Cloudflare 部署配置
- 本地持久化的 session / 配置文件
