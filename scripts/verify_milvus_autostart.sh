#!/bin/bash
# 验证 milvus.service 真的能管住这套容器：
# 停 → 确认全停 → systemctl start → 等健康 → 确认全起
echo "===== A. 当前状态 ====="
systemctl is-enabled milvus.service
systemctl is-active milvus.service
docker ps --filter name=milvus --format '  {{.Names}} | {{.Status}}'

echo
echo "===== B. systemctl stop milvus ====="
systemctl stop milvus.service
sleep 3
echo "  is-active: $(systemctl is-active milvus.service)"
docker ps --filter name=milvus --format '  仍在运行: {{.Names}} | {{.Status}}'
echo "  19530 监听数: $(ss -lnt 2>/dev/null | grep -c ':19530')"

echo
echo "===== C. systemctl start milvus ====="
systemctl start milvus.service
echo "  is-active: $(systemctl is-active milvus.service)"

echo
echo "===== D. 等健康（最多 180 秒）====="
for i in $(seq 1 36); do
  if curl -sf http://localhost:9091/healthz >/dev/null 2>&1; then
    echo "  第 $((i*5)) 秒：healthz OK ✅"
    break
  fi
  sleep 5
done
docker ps --filter name=milvus --format '  {{.Names}} | {{.Status}}'
echo "  19530 监听数: $(ss -lnt 2>/dev/null | grep -c ':19530')"

echo
echo "===== E. 最终自启配置确认 ====="
echo "  milvus.service enabled : $(systemctl is-enabled milvus.service 2>&1)"
echo "  docker.service enabled : $(systemctl is-enabled docker 2>&1)"
echo "  compose restart 策略   :"
grep -n -E 'container_name|restart' /usr/local/src/docker-milvus/docker-compose.yml | sed 's/^/    /'
echo "  systemd 单元路径        : $(ls -l /etc/systemd/system/multi-user.target.wants/milvus.service 2>&1)"
