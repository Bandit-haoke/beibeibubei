#!/bin/bash
# ============================================================================
#  给 Milvus 配置开机自启动（CentOS 7.9 + docker 20.10.8 + docker-compose v1）
#
#  两层保险，都做：
#    1) compose 文件给三个服务加 restart: always
#       —— 兜底：即使不走 systemd，docker 守护进程重启也会把它们拉起来
#    2) systemd 单元 milvus.service
#       —— 主力：保证 etcd → minio → standalone 的顺序，
#          并提供 systemctl start/stop/status milvus 统一入口
#
#  幂等：重复执行不会重复插入 restart 行，也不会覆盖已有的备份。
# ============================================================================
set -u

COMPOSE_DIR=/usr/local/src/docker-milvus
COMPOSE_FILE=$COMPOSE_DIR/docker-compose.yml
UNIT_FILE=/etc/systemd/system/milvus.service
BACKUP=$COMPOSE_FILE.bak.$(date +%Y%m%d)

echo "===== 0. 备份 compose 文件 ====="
if [ -f "$BACKUP" ]; then
  echo "  备份已存在，跳过：$BACKUP"
else
  cp -a "$COMPOSE_FILE" "$BACKUP" && echo "  已备份到 $BACKUP"
fi

echo
echo "===== 1. 给三个服务加 restart: always ====="
if grep -qE '^\s+restart:' "$COMPOSE_FILE"; then
  echo "  文件里已有 restart 策略，跳过修改"
else
  # 在每个 container_name 行后面插入同缩进的 restart: always
  sed -i '/^    container_name: /a\    restart: always' "$COMPOSE_FILE"
  echo "  已插入。改动后的 restart 行："
  grep -n -E 'container_name|restart' "$COMPOSE_FILE" | sed 's/^/    /'
fi

echo
echo "===== 2. 校验 compose 文件语法 ====="
cd "$COMPOSE_DIR" || exit 1
if docker-compose config >/dev/null 2>&1; then
  echo "  docker-compose config 解析通过 ✅"
else
  echo "  ✗ 解析失败，正在回滚："
  cp -a "$BACKUP" "$COMPOSE_FILE"
  docker-compose config 2>&1 | head -5 | sed 's/^/    /'
  exit 1
fi

echo
echo "===== 3. 写 systemd 单元 $UNIT_FILE ====="
cat > "$UNIT_FILE" <<'UNIT'
[Unit]
Description=Milvus standalone (docker-compose @ /usr/local/src/docker-milvus)
Documentation=https://milvus.io/docs
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
# 必须在这里 cd：docker-compose v1 按工作目录找 compose 文件，
# 而 services 里的相对路径 volumes 也依赖它
WorkingDirectory=/usr/local/src/docker-milvus
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose stop
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT
echo "  已写入"

echo
echo "===== 4. 启用并启动 ====="
systemctl daemon-reload
systemctl enable milvus.service 2>&1 | sed 's/^/  /'
systemctl start milvus.service 2>&1 | sed 's/^/  /'
sleep 3

echo
echo "===== 5. 状态 ====="
echo "  is-enabled: $(systemctl is-enabled milvus.service 2>&1)"
echo "  is-active : $(systemctl is-active milvus.service 2>&1)"
echo
echo "  容器："
docker ps --filter name=milvus --format '    {{.Names}} | {{.Status}}' 2>&1

echo
echo "===== 6. 等 Milvus 端口监听（standalone 首次启动要 30~90 秒）====="
for i in $(seq 1 36); do
  if curl -sf http://localhost:9091/healthz >/dev/null 2>&1; then
    echo "  第 $((i*5)) 秒：healthz 通过 ✅"
    break
  fi
  sleep 5
done
echo "  9091 healthz: $(curl -sf http://localhost:9091/healthz 2>&1 | head -1 || echo '未就绪')"
echo "  19530 监听 : $(ss -lntp 2>/dev/null | grep -c ':19530' || echo 0) 个"
