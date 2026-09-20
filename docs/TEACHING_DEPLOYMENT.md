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

先启动 v2 gateway 和 worker。v2 必须使用认证模式，并将 KLayout renderer
配置给 gateway；不配置时，GDS 仍可执行，但 UI 会如实显示 preview unavailable：

```bash
V2_ROOT=/share/home/yuanwenjie/openroad-platform-v2
V2_PYTHONPATH="$V2_ROOT/contracts/src:$V2_ROOT/core/runtime/src:$V2_ROOT/core/registry/src:$V2_ROOT/core/evaluator/src:$V2_ROOT/core/identity/src:$V2_ROOT/core/client/src:$V2_ROOT/core/provenance/src:$V2_ROOT/gateway/src:$V2_ROOT/apps/plan_executor/src"
export PYTHONPATH="$V2_PYTHONPATH"
export OPENROAD_PLATFORM_PREVIEW_COMMAND="/share/home/yuanwenjie/bin/klayout -b -r $V2_ROOT/tools/render-artifact.py"
V2_PLUGINS_ROOT="$(bash scripts/prepare_v2_plugins.sh)"
python3 -m openroad_platform_gateway \
  --state-root /var/lib/openroad-teaching/v2 \
  --plugins-root "$V2_PLUGINS_ROOT" \
  --admissions-root /share/home/yuanwenjie/openroad-platform-v2/admissions \
  --host 127.0.0.1 --port 8700
python3 -m openroad_platform_gateway.worker \
  --state-root /var/lib/openroad-teaching/v2 \
  --plugins-root "$V2_PLUGINS_ROOT" \
  --admissions-root /share/home/yuanwenjie/openroad-platform-v2/admissions
```

第一次启动时先让 gateway 完成数据库初始化，再启动 worker。随后通过
`POST /kernel/auth/register` 创建第一个管理员账号；之后只使用
`/kernel/auth/login` 获得的 v2 token 启动 M1。

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
