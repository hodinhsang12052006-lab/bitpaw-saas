#!/usr/bin/env bash
# Chạy lại TOÀN BỘ bộ test trên server LOCAL (http://127.0.0.1:5001) — không chạm production.
# Mỗi bộ test chạy với server vừa khởi động lại (tránh giới hạn đăng nhập 5 lần/15 phút còn dính từ bộ trước).
# Kết quả: <OUT>/summary.tsv (tên bộ, mã thoát, dòng tổng kết) + log từng bộ.
#
#   bash scripts/run_full_regression.sh <thư mục kết quả>
set -u
cd "$(dirname "$0")/.."
OUT="${1:-audit-results/full_regression}"
mkdir -p "$OUT"
SUMMARY="$OUT/summary.tsv"
: > "$SUMMARY"
RESTART="$HOME/restart_flask.sh"
export PYTHONIOENCODING=utf-8

run() {   # run <tên> <lệnh...>
  local name="$1"; shift
  bash "$RESTART" >/dev/null 2>&1
  local start=$(date +%s)
  timeout 1800 "$@" > "$OUT/$name.log" 2>&1
  local code=$?
  local line
  line=$(grep -E "Tổng kết|Tổng:|Tổng |TOTAL|PASS ·|passed|FAIL$" "$OUT/$name.log" | tail -1 | tr '\t' ' ')
  printf '%s\t%s\t%ss\t%s\n' "$name" "$code" "$(( $(date +%s) - start ))" "$line" | tee -a "$SUMMARY"
}

TENANTS=(
  "nail demo.nails.au.006758@bitpawdemo.com DemoNails2026!"
  "fnb demo.fnb.343602@bitpawdemo.com DemoBitPaw2026!"
  "spa demo.spa.596348@bitpawdemo.com DemoBitPaw2026!"
  "retail demo.retail.596348@bitpawdemo.com DemoBitPaw2026!"
  "karaoke demo.karaoke.071443@bitpawdemo.com DemoBitPaw2026!"
  "hotel demo.hotel.071443@bitpawdemo.com DemoBitPaw2026!"
  "production demo.production.393328@bitpawdemo.com DemoBitPaw2026!"
  "technical demo.technical.393328@bitpawdemo.com DemoBitPaw2026!"
  "office demo.office.784966@bitpawdemo.com DemoBitPaw2026!"
)

# 1. Tách ngành nghề
# (chia 3 lượt x 3 ngành: giới hạn đăng nhập 5 lần/15 phút; script tổng tự khởi động lại server giữa các lượt)
run industry_isolation_1 env NO_SELF_RESTART=1 ONLY=nail,fnb,spa node scripts/industry_isolation_audit.mjs
run industry_isolation_2 env NO_SELF_RESTART=1 ONLY=retail,karaoke,hotel node scripts/industry_isolation_audit.mjs
run industry_isolation_3 env NO_SELF_RESTART=1 ONLY=production,technical,office node scripts/industry_isolation_audit.mjs
# 2. 9 ngành
for ind in nail fnb spa retail karaoke hotel production technical office; do
  run "master_$ind" node "scripts/${ind}_industry_master_audit.mjs"
done
# 3. Bộ Nails đầy đủ + đóng vai thợ/chủ tiệm/khách
for s in nail_business_cycle_e2e nail_shared_modules_audit nail_gap_completeness_audit nail_ai_bot_customer_care_e2e \
         nail_realtime_sse_e2e verify_nail_pos_acceptance nail_visual_audit nail_persona_e2e; do
  run "$s" node "scripts/$s.mjs"
done
# 4. Module dùng chung, landing, yêu cầu CH Play/App Store
run shared_modules_pha6 node scripts/shared_modules_pha6_audit.mjs
run landing_pages node scripts/landing_pages_audit.mjs
ACC="$OUT/store_acc.json"
python scripts/store_test_account.py create "$ACC" > /dev/null 2>&1
run store_compliance env ACC="$ACC" OUT="$OUT/store_shots" node scripts/store_compliance_e2e.mjs
python scripts/store_test_account.py cleanup "$ACC" > "$OUT/store_cleanup.log" 2>&1
# 5. Bản Desktop bán offline (in-process, không cần server)
run desktop_offline python scripts/desktop_offline_e2e.py
# 6. Bảo mật + chịu lỗi + chịu tải (chỉ local)
run security_full python scripts/security_full_audit.py "$OUT/security_full.json"
run security_crash node scripts/security_crash_resilience_audit.mjs
run load_test python scripts/load_test_local.py 100 60 "$OUT/load_test.json"
# 7. Chữ dịch thô + quét toàn trang cho cả 9 ngành
python - <<'PY' > "$OUT/routes.json"
import json, sys
sys.path.insert(0, '.')
from app import app
print(json.dumps([{'rule': r.rule, 'methods': sorted(r.methods), 'args': sorted(r.arguments)} for r in app.url_map.iter_rules()]))
PY
sed -i -n '/^\[{/,$p' "$OUT/routes.json"
for t in "${TENANTS[@]}"; do
  set -- $t
  run "i18n_$1" env TENANT_EMAIL="$2" TENANT_PASSWORD="$3" node scripts/i18n_raw_key_audit.mjs
  run "site_$1" env TENANT="$1" ROUTES="$OUT/routes.json" OUT="$OUT/site_audit" node scripts/full_site_audit.mjs
done
# Dọn dữ liệu test còn sót trong các tiệm demo (khách tiềm năng nhìn thấy) — sao lưu trước khi xoá
python scripts/cleanup_demo_test_leftovers.py --apply "$OUT/demo_leftovers_backup.json" > "$OUT/demo_cleanup.log" 2>&1
tail -2 "$OUT/demo_cleanup.log"
git checkout -- database.db 2>/dev/null
echo "XONG — tổng hợp: $SUMMARY"
