# KAXI ERP

KAXI ERP V1.0，基于 Django、React、PostgreSQL、Redis 和 MinIO。

## fnOS 直接 Compose 部署

1. 下载 [`compose.fnos.yaml`](compose.fnos.yaml)。
2. 打开 fnOS“Docker → Compose/项目 → 新建”。
3. 上传文件或粘贴内容，项目名称填写 `kaxi-erp`。
4. 点击创建并启动。
5. 浏览器打开 `http://飞牛当前IP:8088`。
6. 使用账号 `admin`、密码 `12345678` 登录，并按提示修改密码。

Compose 会自动拉取公开 Docker Hub 镜像。业务数据、队列和文件分别保存在 `postgres_data`、`redis_data`、`minio_data` 命名卷中。

## fnOS 命令部署

```bash
curl -fsSL https://raw.githubusercontent.com/KaXiTreasure/KaXiERP/main/scripts/install-fnos.sh | sudo bash
```

该方式自动生成随机密钥、校验发布包、启动服务并检查健康状态。

## GitHub 拉取部署

```bash
git clone https://github.com/KaXiTreasure/KaXiERP.git
cd KaXiERP
sudo KAXI_PROJECT_DIR=/opt/kaxi-erp KAXI_HTTP_PORT=8088 bash scripts/install-fnos.sh
```

## 部署文件

| 文件 | 用途 |
|---|---|
| `compose.fnos.yaml` | fnOS 图形界面单文件部署 |
| `compose.deploy.yaml` | 使用发布清单和自定义密钥的正式部署 |
| `compose.yaml` | 本地开发基础服务 |

## 常用操作

```bash
# 查看状态
docker compose -f compose.fnos.yaml ps -a

# 查看日志
docker compose -f compose.fnos.yaml logs --tail 100 migrate backend web

# 停止服务并保留数据
docker compose -f compose.fnos.yaml down

# 重新启动
docker compose -f compose.fnos.yaml up -d
```

公网使用时，在 fnOS 中配置 HTTPS 反向代理，并设置 `KAXI_HTTPS_ENABLED=true` 和正式域名 `KAXI_ALLOWED_HOSTS`。

## 文档

- [fnOS 部署 SOP](docs/deployment/fnos-deployment-sop.md)
- [GitHub 拉取本地部署 SOP](docs/deployment/github-local-deployment-sop.md)
- [文档中心](docs/README.md)
- [项目进度](docs/baseline/00_KAXI_ERP_项目进度.md)
- [V1.0 完成性审计](docs/baseline/10_KAXI_ERP_V1.0_完成性审计.md)
- [最新版本与校验文件](https://github.com/KaXiTreasure/KaXiERP/releases/latest)
