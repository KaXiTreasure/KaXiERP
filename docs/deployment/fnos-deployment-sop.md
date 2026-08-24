# KAXI ERP 飞牛 fnOS 部署 SOP

> 默认更新通道：最新稳定版
>
> 默认端口：`8088`
>
> 初始账号：`admin`
>
> 初始密码：`12345678`

## 1. 直接 Compose 部署

1. 确认 [GitHub 最新 Release](https://github.com/KaXiTreasure/KaXiERP/releases/latest) 已发布，并且 Docker Hub 已显示 `backend-latest`、`frontend-latest`。
2. 下载 [`compose.fnos.yaml`](https://raw.githubusercontent.com/KaXiTreasure/KaXiERP/main/compose.fnos.yaml)。
3. 打开 fnOS“Docker → Compose/项目 → 新建”。
4. 上传文件或粘贴内容。
5. 项目名称填写 `kaxi-erp`。
6. 按第 3 节填写生产密钥，点击创建并启动。
7. 等待 `postgres`、`redis`、`minio`、`backend`、`worker`、`scheduler`、`web` 启动。
8. 确认 `minio-init` 和 `migrate` 状态为 `exited (0)`。
9. 打开 `http://飞牛当前IP:8088`，使用初始凭据登录并修改密码。

Compose 自动拉取公开 Docker Hub 镜像并创建以下数据卷：

- `docker.io/kaxitreasure/kaxierp:backend-latest`
- `docker.io/kaxitreasure/kaxierp:frontend-latest`

| 数据卷 | 内容 |
|---|---|
| `postgres_data` | 业务数据与系统配置 |
| `redis_data` | 任务队列 |
| `minio_data` | 图片、文件、Logo、背景和字体 |

## 2. 自定义端口

在 Compose 项目环境变量中设置：

```dotenv
KAXI_HTTP_PORT=18088
```

访问地址相应改为 `http://飞牛当前IP:18088`。

## 3. 设置生产密钥

在首次创建项目时添加以下环境变量，每项使用独立随机值：

```dotenv
KAXI_SECRET_KEY=至少50位随机字符串
KAXI_DB_PASSWORD=数据库强密码
KAXI_S3_ACCESS_KEY=对象存储用户名
KAXI_S3_SECRET_KEY=对象存储强密码
```

数据卷创建后持续使用同一组数据库和对象存储凭据。

## 4. 查看状态与日志

在 fnOS 项目页面查看容器状态和日志。使用终端时执行：

```bash
docker compose -f compose.fnos.yaml ps -a
docker compose -f compose.fnos.yaml logs --tail 100 migrate backend web
```

正常状态：

| 服务 | 状态 |
|---|---|
| `postgres`、`redis`、`minio`、`backend` | running/healthy |
| `worker`、`scheduler`、`web` | running |
| `minio-init`、`migrate` | exited (0) |

## 5. 升级

1. 备份 `postgres_data`、`minio_data` 和 Compose 环境变量。
2. 下载 `main` 分支最新的 `compose.fnos.yaml`。
3. 在 fnOS Compose 项目中替换配置内容。
4. 保留原项目名称和三个命名卷。
5. 点击重新创建或启动。
6. 按第 4 节检查状态和日志。

命令部署可直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/KaXiTreasure/KaXiERP/main/scripts/install-fnos.sh | sudo bash
```

复现或回退到指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/KaXiTreasure/KaXiERP/main/scripts/install-fnos.sh \
  | sudo KAXI_RELEASE_TAG=v1.0.0 bash
```

该脚本完成发布包校验、密钥生成、升级前数据库备份、镜像拉取和健康检查。

## 6. 备份

备份以下内容并复制到另一块存储或另一台设备：

1. PostgreSQL 逻辑备份。
2. `postgres_data` 快照。
3. `minio_data` 快照。
4. Compose 环境变量。
5. 当前 GitHub Release 的镜像清单和校验文件。

命令部署目录的数据库备份命令：

```bash
sudo KAXI_PROJECT_DIR=/vol1/docker/kaxi-erp \
  /vol1/docker/kaxi-erp/scripts/backup-postgres.sh
```

## 7. HTTPS

1. 在 fnOS 反向代理中配置：`https://erp.example.com` → `http://127.0.0.1:8088`。
2. 在 Compose 环境变量中设置：

```dotenv
KAXI_ALLOWED_HOSTS=erp.example.com
KAXI_HTTPS_ENABLED=true
```

3. 重新创建应用容器。
4. 使用 `https://erp.example.com` 访问。

## 8. 故障检查

| 现象 | 操作 |
|---|---|
| 端口占用 | 设置新的 `KAXI_HTTP_PORT` |
| `migrate` 退出码非 0 | 查看 `migrate` 与 `postgres` 日志 |
| Backend 未健康 | 查看 `backend`、`postgres`、`minio` 日志 |
| 页面无法访问 | 检查 `web` 状态、端口和防火墙 |
| 文件无法使用 | 检查 `minio`、`minio-init` 和 `minio_data` |

## 9. 发布校验

校验当前部署材料时，从 [最新 Release](https://github.com/KaXiTreasure/KaXiERP/releases/latest) 下载：

- `kaxi-erp-deploy.zip`
- `kaxi-erp-deploy.zip.sha256`
- `release-images.env`
- `release-images.env.sha256`

按 SHA-256 文件验证后部署。
