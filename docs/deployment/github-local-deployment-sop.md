# KAXI ERP GitHub 拉取部署 SOP

> 默认更新通道：最新稳定版
>
> 适用：Linux、NAS、服务器
>
> 默认目录：`/opt/kaxi-erp`
>
> 默认端口：`8088`

## 1. 准备环境

安装 Git、curl、unzip、OpenSSL、Docker Engine 和 Docker Compose v2，并确认当前账号可执行 `sudo`。

## 2. 拉取并部署

```bash
git clone https://github.com/KaXiTreasure/KaXiERP.git
cd KaXiERP
sudo KAXI_PROJECT_DIR=/opt/kaxi-erp KAXI_HTTP_PORT=8088 bash scripts/install-fnos.sh
```

脚本将：

1. 下载最新 GitHub Release。
2. 验证 SHA-256。
3. 生成生产密钥。
4. 拉取摘要锁定的 Docker Hub 镜像。
5. 初始化数据库和对象存储。
6. 启动服务并执行健康检查。

## 3. 登录

打开：

```text
http://主机IP:8088
```

使用账号 `admin`、密码 `12345678` 登录，并按提示修改密码。

## 4. 验收

```bash
cd /opt/kaxi-erp
sudo docker compose --env-file .env -f compose.deploy.yaml ps -a
sudo docker compose --env-file .env -f compose.deploy.yaml logs --tail 100 migrate backend web
```

验收结果：

- `postgres`、`redis`、`minio`、`backend` 为 `running/healthy`。
- `worker`、`scheduler`、`web` 为 `running`。
- `minio-init`、`migrate` 为 `exited (0)`。

## 5. 自定义目录和端口

```bash
curl -fsSL https://raw.githubusercontent.com/KaXiTreasure/KaXiERP/main/scripts/install-fnos.sh \
  | sudo KAXI_PROJECT_DIR=/srv/kaxi-erp KAXI_HTTP_PORT=18088 bash
```

## 6. 升级

升级到最新稳定版时，在源码目录执行：

```bash
git checkout main
git pull --ff-only
sudo KAXI_PROJECT_DIR=/opt/kaxi-erp bash scripts/install-fnos.sh
```

脚本保留 `.env` 和数据卷，创建数据库备份，然后更新镜像并执行迁移。

仅在复现或回退时指定版本：

```bash
git fetch --tags
git checkout v1.0.0
sudo KAXI_RELEASE_TAG=v1.0.0 KAXI_PROJECT_DIR=/opt/kaxi-erp bash scripts/install-fnos.sh
```

## 7. 备份

```bash
sudo KAXI_PROJECT_DIR=/opt/kaxi-erp \
  /opt/kaxi-erp/scripts/backup-postgres.sh
```

同步备份：

- `/opt/kaxi-erp/backups/postgres/`
- `postgres_data`
- `minio_data`
- `/opt/kaxi-erp/.env`

## 8. 服务操作

```bash
cd /opt/kaxi-erp

# 停止
sudo docker compose --env-file .env -f compose.deploy.yaml stop

# 启动
sudo docker compose --env-file .env -f compose.deploy.yaml start

# 重启应用
sudo docker compose --env-file .env -f compose.deploy.yaml restart backend worker scheduler web
```

## 9. HTTPS

1. 配置域名反向代理到 `http://127.0.0.1:8088`。
2. 编辑 `/opt/kaxi-erp/.env`：

```dotenv
KAXI_ALLOWED_HOSTS=erp.example.com
KAXI_HTTPS_ENABLED=true
```

3. 再次执行升级命令。
4. 访问 `https://erp.example.com`。

## 10. 故障检查

| 现象 | 操作 |
|---|---|
| Release 下载失败 | 检查 GitHub 网络和最新 Release 状态 |
| SHA-256 不一致 | 重新下载发布包和校验文件 |
| 端口占用 | 设置新的 `KAXI_HTTP_PORT` |
| 数据库迁移失败 | 查看 `migrate` 和 `postgres` 日志 |
| 页面无法访问 | 查看 `web`、`backend` 状态及防火墙 |
