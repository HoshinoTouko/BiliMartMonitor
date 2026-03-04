# Frontend

本目录是 BiliMartMonitor 的 Next.js 前端。

## 开发

安装依赖：

```bash
pnpm install
```

启动开发服务器：

```bash
pnpm dev
```

默认访问地址为 [http://localhost:3000](http://localhost:3000)。

## 约定

- 前端通过 `/api/*` 调用后端接口
- 登录态由后端通过 HttpOnly session cookie 维护
- 不要提交 `src/frontend/.env.local` 或任何本地代理配置

## 常用命令

```bash
pnpm lint
pnpm build
```

根目录整体说明见 `README.md`。
