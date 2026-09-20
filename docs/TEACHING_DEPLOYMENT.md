# 教学平台固定部署

## 运行边界

M1 通过 `OPENROAD_V2_URL` 访问 v2 HTTP。v2 kernel 和 worker 只监听
`127.0.0.1`；M1 也默认只监听 `127.0.0.1:8101`。第一次验收使用 SSH
隧道：

```bash
ssh -L 18101:127.0.0.1:8101 -L 18700:127.0.0.1:8700 user@server
```

浏览器打开 `http://127.0.0.1:18101`。

## 固定状态

启动脚本默认使用：

```text
.local/state/openroad-teaching/m1.sqlite
.local/state/openroad-teaching/logs/
.local/state/openroad-teaching/backups/
```

有管理员权限的服务器把 `M1_STATE_ROOT` 设置为
`/var/lib/openroad-teaching`。不把正式数据库放在 `/tmp`，不从历史临时
数据库迁移交付数据。

## 启动

```bash
export OPENROAD_V2_URL=http://127.0.0.1:8700
export M1_STATE_ROOT=/var/lib/openroad-teaching
export M1_HOST=127.0.0.1
export M1_PORT=8101
bash scripts/start_teaching_platform.sh
```

关闭前使用前台进程的 `Ctrl-C`。健康检查：

```bash
python3 scripts/teaching_platform_ops.py health --url http://127.0.0.1:8101
python3 scripts/teaching_platform_ops.py disk --path /var/lib/openroad-teaching
```

## 备份与回滚

在线备份使用 SQLite backup API，并执行 `PRAGMA integrity_check`：

```bash
python3 scripts/teaching_platform_ops.py backup \
  --database /var/lib/openroad-teaching/m1.sqlite \
  --output /var/lib/openroad-teaching/backups/$(date +%Y%m%d-%H%M%S)
```

回滚代码时停止 M1，记录当前 commit，切换到上一个已验收 commit，重新
启动并检查 health；不要覆盖数据库。若数据库 schema 发生改变，先复制
备份到独立目录并运行 integrity check，再由人工决定恢复。

## 公网演示边界

公网 IP 直连只用于临时教师演示，不能作为发布方式：它没有 HTTPS、限流
和完整的多用户运维保障。正式分享应使用 Cloudflare Tunnel/Access 或等价
反向代理，只暴露 M1 入口，v2 和 worker 永远不暴露公网。
