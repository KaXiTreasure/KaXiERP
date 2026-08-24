# KAXI ERP 开发环境

> 状态：现行开发规程
> 更新日期：2026-08-24
> 返回：[文档中心](../README.md)

## 1. 工具链

- Python 3.13。
- PostgreSQL 17。
- Node.js 24 LTS、Corepack 和 pnpm 11。
- Git。
- Redis 与 MinIO：需要后台任务或对象存储联调时启用。

当前 Windows 开发机不以 Docker Desktop、WSL 或硬件虚拟化为前置条件：PostgreSQL、Python 和 Node.js 可原生运行；GitHub Actions 在 Linux Runner 上完成容器构建。

## 2. 后端初始化（Windows PowerShell）

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

确认本机 PostgreSQL 已创建 `kaxi_erp` 数据库和 `kaxi_app` 用户，并让 `.env` 中的密码与本机一致。然后执行：

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py runserver
```

将 `.env` 保存在本机并加入 Git 忽略列表。

## 3. 前端初始化

```powershell
corepack enable
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

## 4. 可选的开发基础设施 Compose

在支持 Docker 的其他开发机上，`compose.yaml` 只启动 PostgreSQL、Redis 和 MinIO：

```bash
docker compose up -d
```

生产环境选择 `compose.fnos.yaml` 直接部署，或使用 `compose.deploy.yaml` 配合 Release 不可变镜像清单部署。

## 5. 提交前质量门

项目根目录执行：

```powershell
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
pnpm lint
pnpm test
pnpm build
```

数据库测试连接真实 PostgreSQL。发布标签会在 GitHub Actions 的隔离 PostgreSQL 服务中重新执行质量门。

## 6. 常用入口

- Django 配置：`backend/config/settings/`。
- 领域代码：`backend/src/kaxi/`。
- 后端测试：`backend/tests/`。
- 前端：`frontend/src/`。
- OpenAPI：`openapi.yaml`。
- CI：`.github/workflows/ci.yml`。
- 镜像发布：`.github/workflows/release-images.yml`。
