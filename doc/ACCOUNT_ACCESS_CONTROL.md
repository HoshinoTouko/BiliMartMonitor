# 账户管理与越权防护

本文档说明当前账户管理的权限边界，以及对应的测试覆盖范围，避免后续改动引入普通用户越权。

## 鉴权模型

- Web 登录成功后，前端会把当前用户名、角色和 Basic Auth token 保存在本地。
- 后端通过 `Authorization: Basic ...` 重新校验用户名和密码，不依赖前端自报角色。
- 所有需要区分“本人”和“管理员”的接口，都以服务端重新鉴权结果为准。

## 权限矩阵

### 所有已登录用户

- 可以访问 `/api/account/me` 查看自己的账户信息。
- 可以访问 `/api/account/me/password` 修改自己的密码。
- 可以访问前端 `/account` 页面中的“我的账户”模块查看自己的账户信息并修改密码。
- 可以访问 `/api/settings/user-notifications?username=<self>` 查看自己的通知配置。
- 可以访问 `/api/settings/user-notifications` 更新自己的通知配置。
- 可以访问 `/api/settings/user-notifications/test` 对自己的通知配置发测试消息。

### 仅管理员

- 可以访问 `/api/account/users` 查看全部账户。
- 可以访问 `/api/account/users`（POST）新建或更新任意账户。
- 可以访问 `/api/account/users/{username}`（DELETE）删除其他账户。
- 可以在前端 `/account` 页面底部看到“账户管理”模块，并在其中查看、创建、编辑、删除其他账户。
- 可以访问 `/api/settings`、`/api/settings/cron`、`/api/settings/logs`、`/api/settings/db-ping` 等系统级接口。

### 明确禁止

- 普通用户读取或修改其他用户的通知配置。
- 普通用户查看、创建、编辑、删除其他账户。
- 普通用户在前端 `/account` 页面看到“账户管理”模块或独立“账户管理”导航入口。
- 普通用户访问系统设置、Cron 状态和数据库探活接口。
- 未登录用户访问任何需要身份信息的账户/通知接口。

## 测试覆盖

当前权限边界由以下测试文件直接覆盖：

- `tests/test_accounts_router.py`
  - 管理员可以查看、新建账户。
  - 普通用户只能查看自己的账户。
  - 普通用户不能列出全部账户、不能新建账户、不能删除其他账户。
- `tests/test_account_page_ui.py`
  - `/account` 页面源码保持“我的账户在上、账户管理在下”的结构。
  - 非管理员分支不会渲染账户管理面板。
  - 顶部导航不再暴露独立“账户管理”入口。
  - `/admin/users` 前端页面会重定向到 `/account`。
- `tests/test_settings_router.py`
  - 普通用户可以读取自己的通知配置。
  - 普通用户不能读取或修改其他用户通知配置。
  - 普通用户不能访问系统设置。
  - 未带鉴权头会被拒绝。

## 维护要求

- 新增账户相关接口时，先定义“本人可做什么、管理员可做什么”，再写路由。
- 不要只在前端隐藏按钮，必须在后端返回 `401` 或 `403`。
- 修改权限逻辑后，必须同步补充或更新上述测试。
