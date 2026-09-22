#!/bin/bash
# Orchestrator: restart Flask giữa mỗi lần login để reset rate-limiter (memory:// per-process,
# 5 login/15 phút/IP) — không đụng gì tới cấu hình rate-limit thật, chỉ né nó lúc test.
# Dùng PID tracking (thay vì pkill -f, không đáng tin trên Windows/git-bash) để đảm bảo luôn
# chỉ có ĐÚNG 1 server sống tại bất kỳ thời điểm nào.
set -e
cd "C:\Users\Acer Nitro\Downloads\Bitpawsofrware"

SERVER_PID=""

kill_port_5001() {
  for pid in $(netstat -ano | grep ":5001" | grep LISTENING | awk '{print $5}' | sort -u); do
    taskkill //F //PID "$pid" 2>/dev/null || true
  done
}

restart_server() {
  if [ -n "$SERVER_PID" ]; then
    taskkill //F //PID "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
  fi
  kill_port_5001
  sleep 1
  rm -f /tmp/flask_server.log
  nohup python3 app.py > /tmp/flask_server.log 2>&1 &
  SERVER_PID=$!
  disown
  local ready=0
  for i in $(seq 1 20); do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:5001/ || echo "000")
    if [ "$http_code" != "000" ]; then ready=1; break; fi
    sleep 1
  done
  if [ "$ready" != "1" ]; then
    echo "FATAL: server did not come up (pid $SERVER_PID)"
    cat /tmp/flask_server.log
    exit 1
  fi
  sleep 1
}

echo "=== [1/11] PUBLIC PAGES ==="
restart_server
node scripts/test_by_map.mjs public

for ind_code in nail spa fnb retail karaoke hotel production technical office; do
  echo "=== INDUSTRY: $ind_code ==="
  restart_server
  node scripts/test_by_map.mjs industry "$ind_code"
done

echo "=== COMMON AUTHENTICATED PAGES (retail account) ==="
restart_server
node scripts/test_by_map.mjs common

echo "=== ALL PHASES DONE ==="
