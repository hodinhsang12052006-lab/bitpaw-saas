# BÁO CÁO QUÉT TIA X TOÀN DIỆN HỆ THỐNG BITPAW OS
> **Thời gian quét:** 2026-07-07  
> **Phương pháp:** Deep Scanner Script (Recursive File Inspection)

---

## 1. CÂY THƯ MỤC HOÀN CHỈNH (COMPLETE DIRECTORY TREE)
Bỏ qua các thư mục hệ thống/bộ nhớ đệm như `.git`, `.vscode`, `__pycache__`, `node_modules`.

```text
├── .cursorrules.txt (0.79 KB)
├── .env.example (0.84 KB)
├── BITPAW_SYSTEM_REPORT.md (10.71 KB)
├── SalesDashboard.jsx (4.48 KB)
├── ad_assistant.py (8.07 KB)
├── ad_suggest_api.py (4.57 KB)
├── ai_context_engine.py (2.48 KB)
├── ai_nurturing_engine.py (23.49 KB)
├── app.py (146.50 KB)
├── auth_service.py (2.25 KB)
├── database/
    ├── bitpaw_network_schema.sql (16.28 KB)
├── database.db (136.00 KB)
├── merge_logic.py (6.51 KB)
├── module_loader.py (1.41 KB)
├── no_test_tay.py (4.93 KB)
├── package-lock.json (39.58 KB)
├── package.json (0.50 KB)
├── postcss.config.js (0.08 KB)
├── requirements.txt (0.09 KB)
├── sales.db (44.00 KB)
├── scan_results.txt (43.20 KB)
├── scratch/
    ├── analyze_chamcong.py (0.56 KB)
    ├── check_and_create_products.py (2.12 KB)
    ├── check_js_syntax.js (1.00 KB)
    ├── check_markers.py (0.61 KB)
    ├── fix_landing.py (3.88 KB)
    ├── full_test_raw_latest.txt (11.27 KB)
    ├── full_test_results.md (13.57 KB)
    ├── full_test_results_latest.json (9.03 KB)
    ├── generate_deep_scan_report.py (5.45 KB)
    ├── list_routes.py (2.54 KB)
    ├── load_test_100_users.py (7.80 KB)
    ├── load_test_results.md (1.57 KB)
    ├── manual_uat_mascot.py (5.73 KB)
    ├── manual_uat_phase0_1.py (5.38 KB)
    ├── manual_uat_phase2.py (2.27 KB)
    ├── search_ai_routes.py (0.36 KB)
    ├── search_hrm.py (0.31 KB)
    ├── search_landing_results.txt (9.19 KB)
    ├── search_scenarios.py (0.18 KB)
    ├── test_ad_assistant.py (2.32 KB)
    ├── test_ai_endpoint.py (1.07 KB)
    ├── test_checkout_debug.py (3.23 KB)
    ├── test_db_settings.py (0.49 KB)
    ├── test_flask_app.py (3.75 KB)
    ├── test_full_suite.py (9.28 KB)
    ├── test_http_requests.py (4.35 KB)
    ├── test_other_modules.py (1.18 KB)
    ├── test_payment_insert.py (2.41 KB)
    ├── test_render_gateway.py (1.04 KB)
    ├── test_report.json (13.56 KB)
    ├── uat_ai_stack.py (8.33 KB)
    ├── uat_crm_nurturing.py (8.42 KB)
    ├── uat_finance_inventory_reports.py (8.28 KB)
    ├── uat_hrm_attendance_payroll.py (7.40 KB)
    ├── uat_mascot_report.md (3.65 KB)
├── seed_supabase_registry.py (17.84 KB)
├── static/
    ├── cho1.jpg (92.45 KB)
    ├── cho1.jpg.jpg (92.45 KB)
    ├── css/
        ├── .gitkeep (0.02 KB)
        ├── input.css (0.06 KB)
        ├── network.css (6.98 KB)
        ├── tailwind.output.css (8261.14 KB)
    ├── images/
        ├── .gitkeep (0.02 KB)
    ├── js/
        ├── .gitkeep (0.02 KB)
        ├── ai_sales_widget.js (53.51 KB)
        ├── chart.min.js (195.93 KB)
        ├── chart.min.js.map (0.00 KB)
        ├── chart.umd.min.js.map (0.00 KB)
        ├── cskh_widget.js (48.00 KB)
        ├── network.js (12.62 KB)
    ├── uploads/
        ├── cho1.jpg.jpg (92.45 KB)
        ├── spa_bg.jpg.webp (21.98 KB)
├── supabase_ai_nurturing_schema.sql (5.09 KB)
├── supabase_client.py (4.90 KB)
├── supabase_modules_map.sql (5.45 KB)
├── supabase_registry_full.sql (5.24 KB)
├── supabase_registry_seed.sql (6.56 KB)
├── supabase_rls.sql (6.11 KB)
├── supabase_runtime_adapter.py (2.54 KB)
├── supabase_schema.sql (9.45 KB)
├── supabase_schema_clean.sql (44.98 KB)
├── supabase_schema_full.sql (26.71 KB)
├── supabase_schema_patch_missing.sql (2.86 KB)
├── supabase_schema_patch_payment_transactions.sql (0.63 KB)
├── supabase_schema_repair_business_id.sql (7.31 KB)
├── supabase_seed_full.sql (9.70 KB)
├── supabase_storage.sql (2.54 KB)
├── tailwind.config.js (1.72 KB)
├── templates/
    ├── ad_assistant.html (44.33 KB)
    ├── add_expense.html (39.28 KB)
    ├── add_product.html (27.21 KB)
    ├── add_spa.html (26.92 KB)
    ├── admin_payment_management.html (45.53 KB)
    ├── ai-studio.html (99.05 KB)
    ├── ai_bot.html (68.43 KB)
    ├── app_chat.html (31.04 KB)
    ├── app_nhanvien.html (88.26 KB)
    ├── backup_restore.html (36.83 KB)
    ├── bangluong.html (47.52 KB)
    ├── baocao_loinhuan.html (33.08 KB)
    ├── booking.html (25.00 KB)
    ├── brand_settings.html (33.40 KB)
    ├── campaign_builder.html (33.50 KB)
    ├── cauhinh_luong.html (22.98 KB)
    ├── chamcong.html (29.32 KB)
    ├── chamcong_congnhan.html (55.80 KB)
    ├── chamcong_fnb.html (52.87 KB)
    ├── chamcong_khachsan.html (40.68 KB)
    ├── chamcong_kythuat.html (53.79 KB)
    ├── chamcong_nail.html (53.78 KB)
    ├── chamcong_spa.html (47.47 KB)
    ├── chamcong_vanphong.html (36.80 KB)
    ├── chat.html (46.48 KB)
    ├── checkout.html (31.37 KB)
    ├── components/
        ├── cskh_global.html (3.57 KB)
    ├── crm.html (37.57 KB)
    ├── crm_automation.html (83.44 KB)
    ├── customer_nurturing.html (39.37 KB)
    ├── dashboard.html (58.49 KB)
    ├── diemdanh.html (15.67 KB)
    ├── ecommerce_sync.html (30.74 KB)
    ├── expense_list.html (16.47 KB)
    ├── fnb_dashboard.html (27.16 KB)
    ├── index.html (102.13 KB)
    ├── inventory_alert.html (37.54 KB)
    ├── karaoke.html (30.92 KB)
    ├── kitchen_display.html (29.50 KB)
    ├── landing.html (244.02 KB)
    ├── landing_fnb.html (130.52 KB)
    ├── landing_hotel.html (129.22 KB)
    ├── landing_hr.html (104.22 KB)
    ├── landing_karaoke.html (105.30 KB)
    ├── landing_nail.current_ai_bad_backup.html (60.46 KB)
    ├── landing_nail.html (132.16 KB)
    ├── landing_office.html (103.42 KB)
    ├── landing_production.html (104.87 KB)
    ├── landing_retail.html (103.05 KB)
    ├── landing_spa.html (130.73 KB)
    ├── landing_technical.html (104.68 KB)
    ├── login.html (29.76 KB)
    ├── map_dashboard.html (53.32 KB)
    ├── network_communities.html (4.45 KB)
    ├── network_cv_builder.html (8.45 KB)
    ├── network_dashboard.html (18.35 KB)
    ├── network_discover.html (8.15 KB)
    ├── network_home.html (12.88 KB)
    ├── network_jobs.html (5.07 KB)
    ├── network_login.html (6.93 KB)
    ├── network_messages.html (5.21 KB)
    ├── network_onboarding.html (17.85 KB)
    ├── network_profile.html (13.22 KB)
    ├── network_register.html (7.49 KB)
    ├── network_services.html (5.21 KB)
    ├── nhanvien.html (46.11 KB)
    ├── omnichannel_connect.html (66.40 KB)
    ├── omnichannel_connect_placeholder.html (10.79 KB)
    ├── payment_gateway.html (69.32 KB)
    ├── payment_history.html (37.62 KB)
    ├── payment_pending.html (24.66 KB)
    ├── payment_success.html (46.14 KB)
    ├── portal.html (33.17 KB)
    ├── pos.html (74.22 KB)
    ├── profit_by_product.html (39.50 KB)
    ├── promotion_management.html (43.47 KB)
    ├── qr_menu.html (45.78 KB)
    ├── quanly_congno.html (39.60 KB)
    ├── quanly_dichvu.html (43.50 KB)
    ├── quanly_kho.html (24.02 KB)
    ├── quanly_thuchi.html (38.03 KB)
    ├── register.html (26.76 KB)
    ├── report.html (43.20 KB)
    ├── sell.html (30.26 KB)
    ├── setup.html (26.93 KB)
    ├── spa.html (59.02 KB)
    ├── staff_management.html (39.67 KB)
    ├── super_admin.html (59.23 KB)
    ├── table_order.html (48.67 KB)
    ├── transcript.jsonl (8463.61 KB)
    ├── user_logs.html (33.45 KB)
├── tenant_engine.py (1.55 KB)
```

---

## 2. BẢN ĐỒ ROUTE (FLASK ROUTES MAP)
Dưới đây là danh sách toàn bộ các API và Route được định nghĩa trong Flask server (`app.py`):

| Dòng | Route Định Nghĩa | Hàm Backend Xử Lý |
| :--- | :--- | :--- |
| 352 | `@app.route('/register', methods=['GET', 'POST'])` | `def register():` |
| 416 | `@app.route('/login', methods=['GET', 'POST'])` | `def login():` |
| 505 | `@app.route('/logout')` | `def logout():` |
| 523 | `@app.route('/api/cskh/config', methods=['GET'])` | `def get_cskh_config():` |
| 539 | `@app.route('/api/cskh/request', methods=['POST'])` | `def create_cskh_request():` |
| 615 | `@app.route('/api/cskh/click', methods=['POST'])` | `def track_cskh_click():` |
| 631 | `@app.route('/api/cskh/feedback', methods=['POST'])` | `def submit_feedback():` |
| 670 | `@app.route('/') / @app.route('/index') / @app.route('/index.html')` | `def home():` |
| 703 | `@app.route('/dashboard')` | `def index():` |
| 799 | `@app.route('/landingpage') / @app.route('/landing')` | `def landingpage():` |
| 804 | `@app.route('/checkout')` | `def public_checkout():` |
| 809 | `@app.route('/landing_nail')` | `def legacy_landing_nail():` |
| 814 | `@app.route('/solutions/<industry_code>')` | `def solutions_page(industry_code):` |
| 825 | `@app.route('/setup', methods=['GET', 'POST'])` | `def setup():` |
| 843 | `@app.route('/add', methods=['GET', 'POST'])` | `def add_product():` |
| 876 | `@app.route('/update_product/<int:id>', methods=['POST'])` | `def update_product(id):` |
| 888 | `@app.route('/delete_product/<int:id>')` | `def delete_product(id):` |
| 895 | `@app.route('/pos')` | `def pos():` |
| 943 | `@app.route('/add_table', methods=['POST'])` | `def add_table():` |
| 955 | `@app.route('/table/<int:table_id>')` | `def view_table(table_id):` |
| 980 | `@app.route('/order_item/<int:table_id>', methods=['POST'])` | `def order_item(table_id):` |
| 994 | `@app.route('/checkout/<int:table_id>')` | `def checkout_table(table_id):` |
| 1033 | `@app.route('/add_expense', methods=['GET', 'POST'])` | `def add_expense():` |
| 1061 | `@app.route('/expense_list')` | `def expense_list():` |
| 1078 | `@app.route('/promotions')` | `def promotions():` |
| 1089 | `@app.route('/add_promotion', methods=['POST'])` | `def add_promotion():` |
| 1107 | `@app.route('/update_promotion/<int:id>', methods=['PUT'])` | `def update_promotion(id):` |
| 1114 | `@app.route('/delete_promotion/<int:id>', methods=['DELETE'])` | `def delete_promotion(id):` |
| 1121 | `@app.route('/staff')` | `def staff_list():` |
| 1127 | `@app.route('/add_staff', methods=['POST'])` | `def add_staff():` |
| 1140 | `@app.route('/update_staff/<int:id>', methods=['PUT'])` | `def update_staff(id):` |
| 1147 | `@app.route('/delete_staff/<int:id>', methods=['DELETE'])` | `def delete_staff(id):` |
| 1154 | `@app.route('/customers')` | `def customers():` |
| 1160 | `@app.route('/add_customer', methods=['POST'])` | `def add_customer():` |
| 1177 | `@app.route('/update_customer/<int:id>', methods=['PUT'])` | `def update_customer(id):` |
| 1184 | `@app.route('/delete_customer/<int:id>', methods=['DELETE'])` | `def delete_customer(id):` |
| 1191 | `@app.route('/payment_transactions')` | `def payment_transactions():` |
| 1197 | `@app.route('/update_payment_status/<int:id>', methods=['POST'])` | `def update_payment_status(id):` |
| 1205 | `@app.route('/spa')` | `def spa():` |
| 1228 | `@app.route('/add_spa', methods=['GET', 'POST'])` | `def add_spa():` |
| 1249 | `@app.route('/delete_spa/<int:id>')` | `def delete_spa(id):` |
| 1255 | `@app.route('/checkout_spa', methods=['POST'])` | `def checkout_spa():` |
| 1282 | `@app.route('/booking') / @app.route('/booking/qr/<spa_id>') / @app.route('/booking/service/<service_id>')` | `def public_booking(spa_id=None, service_id=None):` |
| 1288 | `@app.route('/create_appointment', methods=['POST'])` | `def create_appointment():` |
| 1303 | `@app.route('/karaoke')` | `def karaoke():` |
| 1309 | `@app.route('/toggle_room/<int:room_id>')` | `def toggle_room(room_id):` |
| 1350 | `@app.route('/report')` | `def report():` |
| 1377 | `@app.route('/profit_report')` | `def profit_report():` |
| 1406 | `@app.route('/user_logs')` | `def user_logs():` |
| 1414 | `@app.route('/backup_restore')` | `def backup_restore():` |
| 1419 | `@app.route('/api/backup/create', methods=['POST'])` | `def create_backup():` |
| 1452 | `@app.route('/api/backup/restore', methods=['POST'])` | `def restore_backup():` |
| 1468 | `@app.route('/api/backup/list', methods=['GET'])` | `def list_backups():` |
| 1481 | `@app.route('/qr_menu')` | `def qr_menu_base():` |
| 1486 | `@app.route('/qr_menu/<path:identifier>')` | `def qr_menu(identifier):` |
| 1509 | `@app.route('/api/submit_qr_order', methods=['POST'])` | `def submit_qr_order():` |
| 1576 | `@app.route('/brand_settings', methods=['GET', 'POST'])` | `def brand_settings():` |
| 1607 | `@app.route('/inventory_alert')` | `def inventory_alert():` |
| 1611 | `@app.route('/kitchen_display')` | `def kitchen_display():` |
| 1615 | `@app.route('/ecommerce_sync')` | `def ecommerce_sync():` |
| 1619 | `@app.route('/payment_gateway')` | `def payment_gateway():` |
| 1633 | `@app.route('/api/payment/save_config', methods=['POST'])` | `def api_save_payment_config():` |
| 1661 | `@app.route('/payment_history')` | `def payment_history():` |
| 1665 | `@app.route('/payment_pending')` | `def payment_pending():` |
| 1690 | `@app.route('/api/payment/start', methods=['POST'])` | `def api_payment_start():` |
| 1730 | `@app.route('/api/payment/confirm', methods=['POST'])` | `def api_payment_confirm():` |
| 1808 | `@app.route('/api/payment/cancel', methods=['POST'])` | `def api_payment_cancel():` |
| 1829 | `@app.route('/payment_success')` | `def payment_success():` |
| 1833 | `@app.route('/sell')` | `def sell():` |
| 1838 | `@app.route('/nhanvien')` | `def nhanvien():` |
| 1842 | `@app.route('/bangluong')` | `def bangluong():` |
| 1846 | `@app.route('/chamcong')` | `def chamcong():` |
| 1851 | `@app.route('/chamcong/congnhan') / @app.route('/chamcong_congnhan')` | `def chamcong_congnhan():` |
| 1856 | `@app.route('/chamcong/fnb') / @app.route('/chamcong_fnb')` | `def chamcong_fnb():` |
| 1861 | `@app.route('/chamcong/khachsan') / @app.route('/chamcong_khachsan')` | `def chamcong_khachsan():` |
| 1866 | `@app.route('/chamcong/kythuat') / @app.route('/chamcong_kythuat')` | `def chamcong_kythuat():` |
| 1871 | `@app.route('/chamcong/nail') / @app.route('/chamcong_nail')` | `def chamcong_nail():` |
| 1876 | `@app.route('/chamcong/spa') / @app.route('/chamcong_spa')` | `def chamcong_spa():` |
| 1881 | `@app.route('/chamcong/vanphong') / @app.route('/chamcong_vanphong')` | `def chamcong_vanphong():` |
| 1886 | `@app.route('/chamcong/<industry_code>') / @app.route('/chamcong_<industry_code>')` | `def chamcong_industry(industry_code):` |
| 1894 | `@app.route('/table_order')` | `def table_order():` |
| 1921 | `@app.route('/baocao_loinhuan')` | `def baocao_loinhuan():` |
| 1925 | `@app.route('/cauhinh_luong')` | `def cauhinh_luong():` |
| 1941 | `@app.route('/diemdanh')` | `def diemdanh():` |
| 1945 | `@app.route('/fnb_dashboard')` | `def fnb_dashboard():` |
| 1949 | `@app.route('/portal')` | `def portal():` |
| 1953 | `@app.route('/quanly_congno')` | `def quanly_congno():` |
| 1957 | `@app.route('/quanly_dichvu')` | `def quanly_dichvu():` |
| 1961 | `@app.route('/quanly_kho')` | `def quanly_kho():` |
| 1965 | `@app.route('/quanly_thuchi')` | `def quanly_thuchi():` |
| 1970 | `@app.route('/super_admin') / @app.route('/super-admin')` | `def super_admin():` |
| 1974 | `@app.route('/ai_bot')` | `def ai_bot():` |
| 2050 | `@app.route('/ai-studio') / @app.route('/ai_studio')` | `def ai_studio():` |
| 2054 | `@app.route('/api/ai/studio/generate', methods=['POST'])` | `def secure_ai_generate():` |
| 2093 | `@app.route('/app_chat')` | `def app_chat():` |
| 2097 | `@app.route('/chat')` | `def chat():` |
| 2101 | `@app.route('/crm_automation')` | `def crm_automation():` |
| 2105 | `@app.route('/map_dashboard')` | `def map_dashboard():` |
| 2109 | `@app.route('/app_nhanvien')` | `def app_nhanvien():` |
| 2113 | `@app.route('/api/superadmin/duc_ma', methods=['POST'])` | `def duc_ma():` |
| 2128 | `@app.route('/api/superadmin/get_keys', methods=['GET'])` | `def get_keys():` |
| 2147 | `@app.route('/ai/connect-platforms') / @app.route('/omnichannel_connect')` | `def connect_platforms():` |
| 2152 | `@app.route('/ai/customer-nurturing') / @app.route('/customer_nurturing')` | `def customer_nurturing():` |
| 2157 | `@app.route('/ai/campaign-builder') / @app.route('/campaign_builder')` | `def campaign_builder():` |
| 2161 | `@app.route('/api/ai/nurture/connect-status', methods=['GET'])` | `def nurture_connect_status():` |
| 2231 | `@app.route('/api/ai/nurture/toggle-connection', methods=['POST'])` | `def nurture_toggle_connection():` |
| 2303 | `@app.route('/api/ai/nurture/test-connection', methods=['POST'])` | `def nurture_test_connection():` |
| 2337 | `@app.route('/omnichannel/status', methods=['GET'])` | `def omnichannel_status_all():` |
| 2341 | `@app.route('/omnichannel/status/<channel>', methods=['GET'])` | `def omnichannel_status_single(channel):` |
| 2353 | `@app.route('/omnichannel/connect/<channel>', methods=['GET'])` | `def omnichannel_connect_portal(channel):` |
| 2360 | `@app.route('/omnichannel/callback/<channel>', methods=['GET'])` | `def omnichannel_callback(channel):` |
| 2406 | `@app.route('/omnichannel/disconnect/<channel>', methods=['POST'])` | `def omnichannel_disconnect_api(channel):` |
| 2423 | `@app.route('/omnichannel/test/<channel>', methods=['POST'])` | `def omnichannel_test_api(channel):` |
| 2449 | `@app.route('/api/cskh/lead-submit', methods=['POST'])` | `def cskh_lead_submit():` |
| 2473 | `@app.route('/api/ai/nurture/customers', methods=['GET'])` | `def nurture_customers():` |
| 2519 | `@app.route('/api/ai/nurture/import-data', methods=['POST'])` | `def nurture_import_data():` |
| 2543 | `@app.route('/api/ai/nurture/generate-campaign', methods=['POST'])` | `def nurture_generate_campaign():` |
| 2609 | `@app.route('/api/ai/nurture/approval-queue', methods=['GET'])` | `def nurture_approval_queue():` |
| 2641 | `@app.route('/api/ai/nurture/approve-message', methods=['POST'])` | `def nurture_approve_message():` |
| 2662 | `@app.route('/api/ai/nurture/recommendations', methods=['GET'])` | `def nurture_recommendations():` |
| 2675 | `@app.route('/api/bot/scenarios', methods=['GET'])` | `def get_bot_scenarios():` |
| 2755 | `@app.route('/api/bot/scenarios', methods=['POST'])` | `def create_bot_scenario():` |
| 2787 | `@app.route('/api/bot/scenarios/<scenario_id>', methods=['GET'])` | `def get_single_bot_scenario(scenario_id):` |
| 2821 | `@app.route('/api/bot/scenarios/<scenario_id>', methods=['PUT'])` | `def update_bot_scenario(scenario_id):` |
| 2853 | `@app.route('/api/bot/scenarios/<scenario_id>', methods=['DELETE'])` | `def delete_bot_scenario(scenario_id):` |
| 2866 | `@app.route('/api/bot/scenarios/<scenario_id>/toggle', methods=['POST'])` | `def toggle_bot_scenario(scenario_id):` |
| 2888 | `@app.route('/api/bot/scenarios/<scenario_id>/test', methods=['POST'])` | `def test_bot_scenario(scenario_id):` |
| 2975 | `@app.route('/api/bot/logs', methods=['GET'])` | `def get_bot_logs():` |
| 3025 | `@app.route('/api/chamcong/checkin', methods=['POST'])` | `def api_checkin():` |
| 3078 | `@app.route('/api/chamcong/checkout', methods=['POST'])` | `def api_checkout():` |
| 3129 | `@app.route('/api/chamcong/status', methods=['GET'])` | `def api_attendance_status():` |
| 3173 | `@app.route('/api/payroll/calculate', methods=['POST'])` | `def api_calculate_payroll():` |
| 3196 | `@app.route('/expense')` | `def expense_alias():` |
| 3325 | `@app.route('/network')` | `def network_home():` |
| 3337 | `@app.route('/network/login', methods=['GET', 'POST'])` | `def network_login():` |
| 3356 | `@app.route('/network/register', methods=['GET', 'POST'])` | `def network_register():` |
| 3377 | `@app.route('/network/onboarding', methods=['GET', 'POST'])` | `def network_onboarding():` |
| 3410 | `@app.route('/network/profile')` | `def network_profile():` |
| 3428 | `@app.route('/network/dashboard')` | `def network_dashboard():` |
| 3436 | `@app.route('/network/discover')` | `def network_discover():` |
| 3442 | `@app.route('/network/jobs')` | `def network_jobs():` |
| 3446 | `@app.route('/network/services')` | `def network_services():` |
| 3450 | `@app.route('/network/communities')` | `def network_communities():` |
| 3454 | `@app.route('/network/messages')` | `def network_messages():` |
| 3461 | `@app.route('/network/cv-builder')` | `def network_cv_builder():` |
| 3481 | `@app.route('/api/workspace/generate-qr', methods=['POST'])` | `def generate_qr():` |
| 3514 | `@app.route('/api/workspace/validate-qr', methods=['POST'])` | `def validate_qr():` |

---

## 3. LUỒNG XÁC THỰC CHI TIẾT (AUTH FLOW ANALYSIS)

Hệ thống quản lý xác thực được phân tách làm hai giải pháp độc lập tùy theo phân hệ giao diện:

### A. Luồng Đăng nhập/Đăng ký khối Quản trị (Admin/OS Portal)
*   **Giao diện chính:** Tệp `templates/index.html` (sử dụng hai tab `login` và `register` phục vụ đăng nhập/đăng ký mặc định) hoặc hai tệp giao diện độc lập [login.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/login.html) và [register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/register.html).
*   **Cơ chế hoạt động:**
    1.  Khách hàng/Admin nhập form và gửi `POST` request trực tiếp về Flask server tại các endpoints `@app.route('/login')` hoặc `@app.route('/register')`.
    2.  Tại Backend, Flask sử dụng thư viện **Supabase Python SDK** (`supabase.auth.sign_in_with_password` hoặc `supabase.auth.sign_up`) để kiểm tra tài khoản trên Cloud.
    3.  Đồng thời, khi đăng ký, Backend sẽ đối chiếu mã kích hoạt bản quyền `license_key` trực tiếp trên cơ sở dữ liệu SQLite local (`database.db`, bảng `kho_license`).
    4.  Nếu đăng nhập/đăng ký thành công, Flask lưu thông tin định danh và quyền của người dùng vào `session` phía máy chủ (`session['user_id']`, `session['business_mode']`) để quản lý quyền truy cập.

### B. Luồng Xác thực khối Nhân viên (Employee Mini-App)
*   **Giao diện chính:** [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html) (truy cập thông qua route GET `/app_nhanvien`).
*   **Cơ chế hoạt động:**
    1.  **Xác thực không mật khẩu (Passwordless/Token Code):** Phân hệ nhân viên không sử dụng mật khẩu. Thay vào đó, nhân viên đăng nhập bằng **Mã Nhân Viên (Employee Code - ví dụ: NV001)**.
    2.  **Xử lý thuần Client-side:** Trình duyệt tải tệp `app_nhanvien.html` và sử dụng trực tiếp thư viện **Supabase Javascript SDK** (`@supabase/supabase-js`) để gọi API từ Supabase Cloud.
    3.  **Auto-Login (Tích hợp PawBook):**
        *   Khi mở trang với định dạng `/app_nhanvien?token=NV001`, mã Javascript sẽ bắt sự kiện `window.onload` và lấy giá trị `token` từ tham số URL.
        *   Nó gửi câu lệnh truy vấn trực tiếp lên Supabase PostgreSQL: `supabase.from('employees').select('*').eq('ma_nv', token)`
        *   Nếu nhân sự tồn tại, JS tự động ghi thông tin vào `localStorage`, lưu vào biến toàn cục `currentUser` và gọi `vaoAppNgay()`, ẩn hoàn toàn màn hình xác thực mà không cần đi qua cổng Flask backend.

---
*Báo cáo Deep Scan được lập tự động bởi Antigravity AI.*
