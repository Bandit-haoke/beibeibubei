#!/bin/bash
# 探测虚拟机里 MySQL 的真实 root 密码线索
echo "===== 主机信息 ====="
hostname
uname -r
(cat /etc/redhat-release 2>/dev/null || head -2 /etc/os-release) 2>/dev/null

echo
echo "===== mysql 容器的环境变量 ====="
docker inspect mysql --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1 | grep -iE 'mysql|pass|user|root'

echo
echo "===== mysql 容器的启动命令 ====="
docker inspect mysql --format '{{json .Config.Cmd}} {{json .Config.Entrypoint}}' 2>&1

echo
echo "===== 所有容器 env 中的密码线索 ====="
for c in $(docker ps --format '{{.Names}}'); do
  hits=$(docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -iE 'pass|pwd|secret|datasource|jdbc' | head -6)
  if [ -n "$hits" ]; then
    echo "--- $c ---"
    echo "$hits"
  fi
done

echo
echo "===== 查找 compose / 配置文件 ====="
find /root /opt /home -maxdepth 4 \( -name '*.yml' -o -name '*.yaml' -o -name '*.properties' -o -name '*.cnf' -o -name '*.sh' \) 2>/dev/null | head -40

echo
echo "===== grep 密码（yml/properties/cnf 里的 mysql 密码）====="
grep -rIn -iE '(password|pwd)[^a-z]{0,4}[=:][^=:]{2,40}' \
  --include='*.yml' --include='*.yaml' --include='*.properties' --include='*.cnf' \
  /root /opt /home 2>/dev/null | grep -iE 'mysql|root|123|pass' | head -30

echo
echo "===== 测试 mysql 容器内免密登录 ====="
docker exec mysql sh -c 'mysql -uroot -e "SELECT 1" 2>&1 | head -3' 2>&1

echo
echo "===== 测试 mysql 容器内 root/your-vm-password ====="
docker exec mysql sh -c 'mysql -uroot -pyour-vm-password -e "SELECT VERSION(), CURRENT_USER()" 2>&1 | head -3' 2>&1

echo
echo "===== 测试 mysql 容器内 root/123456 ====="
docker exec mysql sh -c 'mysql -uroot -p123456 -e "SELECT VERSION(), CURRENT_USER()" 2>&1 | head -3' 2>&1
