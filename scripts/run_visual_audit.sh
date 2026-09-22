#!/bin/bash
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
  sleep 3
  rm -f /tmp/flask_server.log
  nohup python3 app.py > /tmp/flask_server.log 2>&1 &
  SERVER_PID=$!
  disown
  for i in $(seq 1 30); do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:5001/ || echo "000")
    if [ "$http_code" != "000" ]; then break; fi
    sleep 1
  done
  sleep 3
}

run_with_retry() {
  local ind="$1"
  local attempt=1
  while [ $attempt -le 3 ]; do
    echo "=== INDUSTRY: $ind (attempt $attempt) ==="
    restart_server
    if node scripts/visual_industry_audit.mjs "$ind"; then
      return 0
    fi
    echo "!!! $ind attempt $attempt FAILED, retrying !!!"
    attempt=$((attempt+1))
  done
  echo "FATAL: $ind failed after 3 attempts"
  return 1
}

for ind in nail spa fnb retail karaoke hotel production technical office; do
  run_with_retry "$ind"
done

echo "=== ALL VISUAL AUDIT DONE ==="
