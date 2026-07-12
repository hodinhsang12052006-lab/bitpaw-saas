# MASTER HANDOVER REPORT - BÁO CÁO BÀN GIAO TOÀN DIỆN
> **Thời gian thực hiện:** 2026-07-13  
> **Người thực hiện:** Tech Lead Antigravity AI  
> **Phương thức:** Phân tích mã nguồn tĩnh toàn diện (Static Code Analysis - 100% Files)

---

## 1. BẢN ĐỒ MAPPING ROUTE BACKEND & TEMPLATE FRONTEND

Bảng dưới đây thống kê toàn bộ các Flask Routes được tìm thấy trong hệ thống, hàm xử lý tương ứng, và file HTML được render ra phía Client.

| File Nguồn | Dòng | Route API | Methods | Hàm Xử Lý | HTML Template Render |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `app.py` | 351 | `/register` | `GET, POST` | `register` | [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html) |
| `app.py` | 415 | `/login` | `GET, POST` | `login` | [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html) |
| `app.py` | 504 | `/logout` | `GET` | `logout` | *Không render (API JSON)* |
| `app.py` | 522 | `/api/cskh/config` | `GET` | `get_cskh_config` | *Không render (API JSON)* |
| `app.py` | 538 | `/api/cskh/request` | `POST` | `create_cskh_request` | *Không render (API JSON)* |
| `app.py` | 614 | `/api/cskh/click` | `POST` | `track_cskh_click` | [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html) |
| `app.py` | 630 | `/api/cskh/feedback` | `POST` | `submit_feedback` | [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html) |
| `app.py` | 669 | `/index.html` | `GET` | `home` | [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html) |
| `app.py` | 702 | `/dashboard` | `GET` | `index` | [dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/dashboard.html), [landing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing.html) |
| `app.py` | 798 | `/landing` | `GET` | `landingpage` | [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html), [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html), [checkout.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/checkout.html), [landing_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_nail.html), [landing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing.html) |
| `app.py` | 803 | `/checkout` | `GET` | `public_checkout` | [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html), [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html), [landing_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_nail.html), [checkout.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/checkout.html) |
| `app.py` | 808 | `/landing_nail` | `GET` | `legacy_landing_nail` | [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html), [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html), [landing_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_nail.html) |
| `app.py` | 813 | `/solutions/<industry_code>` | `GET` | `solutions_page` | [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html), [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html) |
| `app.py` | 824 | `/setup` | `GET, POST` | `setup` | [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html), [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html), [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html) |
| `app.py` | 842 | `/add` | `GET, POST` | `add_product` | [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html), [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html) |
| `app.py` | 875 | `/update_product/<int:id>` | `POST` | `update_product` | [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html) |
| `app.py` | 887 | `/delete_product/<int:id>` | `GET` | `delete_product` | [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html) |
| `app.py` | 894 | `/pos` | `GET` | `pos` | [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html) |
| `app.py` | 942 | `/add_table` | `POST` | `add_table` | [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html) |
| `app.py` | 954 | `/table/<int:table_id>` | `GET` | `view_table` | [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [add_expense.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_expense.html) |
| `app.py` | 979 | `/order_item/<int:table_id>` | `POST` | `order_item` | [expense_list.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/expense_list.html), [add_expense.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_expense.html), [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html) |
| `app.py` | 993 | `/checkout/<int:table_id>` | `GET` | `checkout_table` | [expense_list.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/expense_list.html), [add_expense.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_expense.html), [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html) |
| `app.py` | 1032 | `/add_expense` | `GET, POST` | `add_expense` | [add_expense.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_expense.html), [expense_list.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/expense_list.html), [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1060 | `/expense_list` | `GET` | `expense_list` | [expense_list.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/expense_list.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html), [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html) |
| `app.py` | 1077 | `/promotions` | `GET` | `promotions` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html), [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html) |
| `app.py` | 1088 | `/add_promotion` | `POST` | `add_promotion` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1106 | `/update_promotion/<int:id>` | `PUT` | `update_promotion` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1113 | `/delete_promotion/<int:id>` | `DELETE` | `delete_promotion` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1120 | `/staff` | `GET` | `staff_list` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1126 | `/add_staff` | `POST` | `add_staff` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1139 | `/update_staff/<int:id>` | `PUT` | `update_staff` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1146 | `/delete_staff/<int:id>` | `DELETE` | `delete_staff` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1153 | `/customers` | `GET` | `customers` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html) |
| `app.py` | 1166 | `/add_customer` | `POST` | `add_customer` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html) |
| `app.py` | 1183 | `/update_customer/<int:id>` | `PUT` | `update_customer` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1190 | `/delete_customer/<int:id>` | `DELETE` | `delete_customer` | [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1197 | `/payment_transactions` | `GET` | `payment_transactions` | [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html), [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html) |
| `app.py` | 1210 | `/update_payment_status/<int:id>` | `POST` | `update_payment_status` | [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1218 | `/spa` | `GET` | `spa` | [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1241 | `/add_spa` | `GET, POST` | `add_spa` | [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1262 | `/delete_spa/<int:id>` | `GET` | `delete_spa` | [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1268 | `/checkout_spa` | `POST` | `checkout_spa` | [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1295 | `/booking/service/<service_id>` | `GET` | `public_booking` | [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html) |
| `app.py` | 1301 | `/create_appointment` | `POST` | `create_appointment` | [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html) |
| `app.py` | 1316 | `/karaoke` | `GET` | `karaoke` | [profit_by_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/profit_by_product.html), [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html), [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html) |
| `app.py` | 1322 | `/toggle_room/<int:room_id>` | `GET` | `toggle_room` | [user_logs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/user_logs.html), [profit_by_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/profit_by_product.html), [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html) |
| `app.py` | 1363 | `/report` | `GET` | `report` | [user_logs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/user_logs.html), [profit_by_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/profit_by_product.html), [backup_restore.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/backup_restore.html), [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html) |
| `app.py` | 1390 | `/profit_report` | `GET` | `profit_report` | [user_logs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/user_logs.html), [profit_by_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/profit_by_product.html), [backup_restore.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/backup_restore.html) |
| `app.py` | 1425 | `/user_logs` | `GET` | `user_logs` | [user_logs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/user_logs.html), [backup_restore.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/backup_restore.html), [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1433 | `/backup_restore` | `GET` | `backup_restore` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html), [backup_restore.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/backup_restore.html) |
| `app.py` | 1438 | `/api/backup/create` | `POST` | `create_backup` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1471 | `/api/backup/restore` | `POST` | `restore_backup` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1487 | `/api/backup/list` | `GET` | `list_backups` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1500 | `/qr_menu` | `GET` | `qr_menu_base` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1505 | `/qr_menu/<path:identifier>` | `GET` | `qr_menu` | [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html) |
| `app.py` | 1528 | `/api/submit_qr_order` | `POST` | `submit_qr_order` | *Không render (API JSON)* |
| `app.py` | 1595 | `/brand_settings` | `GET, POST` | `brand_settings` | [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html), [kitchen_display.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/kitchen_display.html), [inventory_alert.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/inventory_alert.html), [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html), [brand_settings.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/brand_settings.html), [ecommerce_sync.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ecommerce_sync.html) |
| `app.py` | 1633 | `/inventory_alert` | `GET` | `inventory_alert` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html), [kitchen_display.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/kitchen_display.html), [inventory_alert.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/inventory_alert.html), [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html), [ecommerce_sync.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ecommerce_sync.html) |
| `app.py` | 1637 | `/kitchen_display` | `GET` | `kitchen_display` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html), [kitchen_display.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/kitchen_display.html), [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html), [ecommerce_sync.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ecommerce_sync.html) |
| `app.py` | 1641 | `/ecommerce_sync` | `GET` | `ecommerce_sync` | [ecommerce_sync.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ecommerce_sync.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html), [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html), [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html) |
| `app.py` | 1645 | `/payment_gateway` | `GET` | `payment_gateway` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html), [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html) |
| `app.py` | 1659 | `/api/payment/save_config` | `POST` | `api_save_payment_config` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html) |
| `app.py` | 1687 | `/payment_history` | `GET` | `payment_history` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html), [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html) |
| `app.py` | 1691 | `/payment_pending` | `GET` | `payment_pending` | [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html) |
| `app.py` | 1716 | `/api/payment/start` | `POST` | `api_payment_start` | *Không render (API JSON)* |
| `app.py` | 1756 | `/api/payment/confirm` | `POST` | `api_payment_confirm` | [sell.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/sell.html), [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [payment_success.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_success.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html) |
| `app.py` | 1834 | `/api/payment/cancel` | `POST` | `api_payment_cancel` | [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [payment_success.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_success.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [sell.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/sell.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1855 | `/payment_success` | `GET` | `payment_success` | [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [payment_success.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_success.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [sell.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/sell.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1859 | `/sell` | `GET` | `sell` | [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [sell.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/sell.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1864 | `/nhanvien` | `GET` | `nhanvien` | [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1868 | `/bangluong` | `GET` | `bangluong` | [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1872 | `/chamcong` | `GET` | `chamcong` | [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1877 | `/chamcong_congnhan` | `GET` | `chamcong_congnhan` | [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html) |
| `app.py` | 1882 | `/chamcong_fnb` | `GET` | `chamcong_fnb` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1887 | `/chamcong_khachsan` | `GET` | `chamcong_khachsan` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1892 | `/chamcong_kythuat` | `GET` | `chamcong_kythuat` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1897 | `/chamcong_nail` | `GET` | `chamcong_nail` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1902 | `/chamcong_spa` | `GET` | `chamcong_spa` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1907 | `/chamcong_vanphong` | `GET` | `chamcong_vanphong` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1912 | `/chamcong_<industry_code>` | `GET` | `chamcong_industry` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1920 | `/table_order` | `GET` | `table_order` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1947 | `/baocao_loinhuan` | `GET` | `baocao_loinhuan` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1951 | `/cauhinh_luong` | `GET` | `cauhinh_luong` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1967 | `/diemdanh` | `GET` | `diemdanh` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1971 | `/fnb_dashboard` | `GET` | `fnb_dashboard` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html) |
| `app.py` | 1975 | `/portal` | `GET` | `portal` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html) |
| `app.py` | 1979 | `/quanly_congno` | `GET` | `quanly_congno` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html) |
| `app.py` | 1983 | `/quanly_dichvu` | `GET` | `quanly_dichvu` | [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html), [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html) |
| `app.py` | 1987 | `/quanly_kho` | `GET` | `quanly_kho` | [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html) |
| `app.py` | 1991 | `/quanly_thuchi` | `GET` | `quanly_thuchi` | [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html), [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html) |
| `app.py` | 1996 | `/super-admin` | `GET` | `super_admin` | [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html) |
| `app.py` | 2000 | `/ai_bot` | `GET` | `ai_bot` | [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html), [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html) |
| `app.py` | 2076 | `/ai_studio` | `GET` | `ai_studio` | [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html) |
| `app.py` | 2080 | `/api/ai/studio/generate` | `POST` | `secure_ai_generate` | [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html) |
| `app.py` | 2119 | `/app_chat` | `GET` | `app_chat` | [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html), [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html) |
| `app.py` | 2123 | `/chat` | `GET` | `chat` | [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html) |
| `app.py` | 2127 | `/crm_automation` | `GET` | `crm_automation` | [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html) |
| `app.py` | 2131 | `/map_dashboard` | `GET` | `map_dashboard` | [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html), [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html) |
| `app.py` | 2135 | `/app_nhanvien` | `GET` | `app_nhanvien` | [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html) |
| `app.py` | 2139 | `/api/superadmin/duc_ma` | `POST` | `duc_ma` | [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html) |
| `app.py` | 2154 | `/api/superadmin/get_keys` | `GET` | `get_keys` | [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html) |
| `app.py` | 2173 | `/omnichannel_connect` | `GET` | `connect_platforms` | [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html), [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html) |
| `app.py` | 2178 | `/customer_nurturing` | `GET` | `customer_nurturing` | [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html), [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html) |
| `app.py` | 2183 | `/campaign_builder` | `GET` | `campaign_builder` | [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html) |
| `app.py` | 2187 | `/api/ai/nurture/connect-status` | `GET` | `nurture_connect_status` | *Không render (API JSON)* |
| `app.py` | 2257 | `/api/ai/nurture/toggle-connection` | `POST` | `nurture_toggle_connection` | *Không render (API JSON)* |
| `app.py` | 2329 | `/api/ai/nurture/test-connection` | `POST` | `nurture_test_connection` | [omnichannel_connect_placeholder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect_placeholder.html) |
| `app.py` | 2363 | `/omnichannel/status` | `GET` | `omnichannel_status_all` | [omnichannel_connect_placeholder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect_placeholder.html) |
| `app.py` | 2367 | `/omnichannel/status/<channel>` | `GET` | `omnichannel_status_single` | [omnichannel_connect_placeholder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect_placeholder.html) |
| `app.py` | 2379 | `/omnichannel/connect/<channel>` | `GET` | `omnichannel_connect_portal` | [omnichannel_connect_placeholder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect_placeholder.html) |
| `app.py` | 2386 | `/omnichannel/callback/<channel>` | `GET` | `omnichannel_callback` | *Không render (API JSON)* |
| `app.py` | 2432 | `/omnichannel/disconnect/<channel>` | `POST` | `omnichannel_disconnect_api` | *Không render (API JSON)* |
| `app.py` | 2449 | `/omnichannel/test/<channel>` | `POST` | `omnichannel_test_api` | *Không render (API JSON)* |
| `app.py` | 2475 | `/api/cskh/lead-submit` | `POST` | `cskh_lead_submit` | *Không render (API JSON)* |
| `app.py` | 2499 | `/api/ai/nurture/customers` | `GET` | `nurture_customers` | *Không render (API JSON)* |
| `app.py` | 2545 | `/api/ai/nurture/import-data` | `POST` | `nurture_import_data` | *Không render (API JSON)* |
| `app.py` | 2569 | `/api/ai/nurture/generate-campaign` | `POST` | `nurture_generate_campaign` | *Không render (API JSON)* |
| `app.py` | 2635 | `/api/ai/nurture/approval-queue` | `GET` | `nurture_approval_queue` | *Không render (API JSON)* |
| `app.py` | 2667 | `/api/ai/nurture/approve-message` | `POST` | `nurture_approve_message` | *Không render (API JSON)* |
| `app.py` | 2688 | `/api/ai/nurture/recommendations` | `GET` | `nurture_recommendations` | *Không render (API JSON)* |
| `app.py` | 2701 | `/api/bot/scenarios` | `GET` | `get_bot_scenarios` | *Không render (API JSON)* |
| `app.py` | 2781 | `/api/bot/scenarios` | `POST` | `create_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 2813 | `/api/bot/scenarios/<scenario_id>` | `GET` | `get_single_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 2847 | `/api/bot/scenarios/<scenario_id>` | `PUT` | `update_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 2879 | `/api/bot/scenarios/<scenario_id>` | `DELETE` | `delete_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 2892 | `/api/bot/scenarios/<scenario_id>/toggle` | `POST` | `toggle_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 2914 | `/api/bot/scenarios/<scenario_id>/test` | `POST` | `test_bot_scenario` | *Không render (API JSON)* |
| `app.py` | 3001 | `/api/bot/logs` | `GET` | `get_bot_logs` | *Không render (API JSON)* |
| `app.py` | 3051 | `/api/chamcong/checkin` | `POST` | `api_checkin` | *Không render (API JSON)* |
| `app.py` | 3104 | `/api/chamcong/checkout` | `POST` | `api_checkout` | *Không render (API JSON)* |
| `app.py` | 3155 | `/api/chamcong/status` | `GET` | `api_attendance_status` | *Không render (API JSON)* |
| `app.py` | 3199 | `/api/payroll/calculate` | `POST` | `api_calculate_payroll` | *Không render (API JSON)* |
| `app.py` | 3222 | `/expense` | `GET` | `expense_alias` | *Không render (API JSON)* |
| `app.py` | 3351 | `/network` | `GET` | `network_home` | [network_login.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_login.html), [network_home.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_home.html), [network_onboarding.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_onboarding.html), [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_profile.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_profile.html), [network_register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_register.html) |
| `app.py` | 3363 | `/network/login` | `GET, POST` | `network_login` | [network_login.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_login.html), [network_onboarding.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_onboarding.html), [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_profile.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_profile.html), [network_register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_register.html) |
| `app.py` | 3382 | `/network/register` | `GET, POST` | `network_register` | [network_onboarding.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_onboarding.html), [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_profile.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_profile.html), [network_register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_register.html) |
| `app.py` | 3403 | `/network/onboarding` | `GET, POST` | `network_onboarding` | [network_onboarding.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_onboarding.html), [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html), [network_profile.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_profile.html) |
| `app.py` | 3436 | `/network/profile` | `GET` | `network_profile` | [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html), [network_profile.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_profile.html) |
| `app.py` | 3454 | `/network/dashboard` | `GET` | `network_dashboard` | [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_dashboard.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html) |
| `app.py` | 3462 | `/network/discover` | `GET` | `network_discover` | [network_discover.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_discover.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html) |
| `app.py` | 3468 | `/network/jobs` | `GET` | `network_jobs` | [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html), [network_jobs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_jobs.html), [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html) |
| `app.py` | 3472 | `/network/services` | `GET` | `network_services` | [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_services.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_services.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html) |
| `app.py` | 3476 | `/network/communities` | `GET` | `network_communities` | [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html), [network_communities.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_communities.html) |
| `app.py` | 3480 | `/network/messages` | `GET` | `network_messages` | [network_messages.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_messages.html), [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html) |
| `app.py` | 3487 | `/network/cv-builder` | `GET` | `network_cv_builder` | [network_cv_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/network_cv_builder.html) |
| `app.py` | 3507 | `/api/workspace/generate-qr` | `POST` | `generate_qr` | *Không render (API JSON)* |
| `app.py` | 3540 | `/api/workspace/validate-qr` | `POST` | `validate_qr` | *Không render (API JSON)* |
| `ad_assistant.py` | 95 | `/` | `GET` | `index` | [ad_assistant.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ad_assistant.html) |
| `ad_assistant.py` | 100 | `/api/suggest` | `POST` | `suggest` | *Không render (API JSON)* |
| `ad_assistant.py` | 131 | `/api/create-campaign` | `POST` | `create_campaign` | *Không render (API JSON)* |
| `ad_assistant.py` | 178 | `/api/campaigns` | `GET` | `list_campaigns` | *Không render (API JSON)* |
| `ad_suggest_api.py` | 57 | `/ad-suggest` | `POST` | `ad_suggest` | *Không render (API JSON)* |

---

## 2. PHÂN TÍCH CHI TIẾT TẤT CẢ FILE TEMPLATES HTML

Tổng số file HTML được quét: **78**

### 📄 [landing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing.html)
*   **Kích thước:** 232.28 KB (3398 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ✅ Có
*   **Được render bởi Route:** `/dashboard` (app.py:702), `/landing` (app.py:798)
*   **Biến Jinja2 tiêu biểu:** `url_for('solutions_page', industry_code='nail'), url_for('solutions_page', industry_code='office'), url_for('solutions_page', industry_code='spa'), url_for('solutions_page', industry_code='fnb'), url_for('solutions_page', industry_code='karaoke'), url_for('static', filename='css/tailwind.output.css'), url_for('solutions_page', industry_code='hr'), url_for('solutions_page', industry_code='technical'), url_for('solutions_page', industry_code='production'), url_for('solutions_page', industry_code='hotel')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, togglePricing, changeLanguage, closeModal, toggleMobileMenu, openModal, changeText, getLang`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_nail.html)
*   **Kích thước:** 128.31 KB (1718 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/landing` (app.py:798), `/checkout` (app.py:803), `/landing_nail` (app.py:808)
*   **Biến Jinja2 tiêu biểu:** `url_for('register'), url_for('chamcong_industry', industry_code='nail'), url_for('staff_list'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('crm_automation'), url_for('landingpage'), url_for('public_booking'), url_for('quanly_dichvu')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateRealtime, initThreeJS`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_spa.html)
*   **Kích thước:** 126.61 KB (1652 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('campaign_builder'), url_for('register'), url_for('chamcong_spa'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('crm_automation'), url_for('landingpage'), url_for('pos'), url_for('add_spa'), url_for('baocao_loinhuan')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateRealtime, initThreeJS`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_fnb.html)
*   **Kích thước:** 126.57 KB (1651 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong_fnb'), url_for('qr_menu_base'), url_for('kitchen_display'), url_for('register'), url_for('campaign_builder'), url_for('baocao_loinhuan'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('landingpage'), url_for('pos')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateRealtime, initThreeJS`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_hotel.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_hotel.html)
*   **Kích thước:** 125.26 KB (1632 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('nhanvien'), url_for('campaign_builder'), url_for('register'), url_for('customers'), url_for('baocao_loinhuan'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('landingpage'), url_for('pos'), url_for('quanly_kho')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateRealtime, initThreeJS`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_karaoke.html)
*   **Kích thước:** 102.29 KB (1447 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong_fnb'), url_for('register'), url_for('payment_gateway'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('karaoke'), url_for('landingpage'), url_for('baocao_loinhuan')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateBill, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_production.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_production.html)
*   **Kích thước:** 101.55 KB (1431 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('register'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('inventory_alert'), url_for('report'), url_for('landingpage'), url_for('bangluong'), url_for('chamcong_congnhan'), url_for('quanly_kho')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateProductionPayroll, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_technical.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_technical.html)
*   **Kích thước:** 101.33 KB (1438 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('map_dashboard'), url_for('register'), url_for('baocao_loinhuan'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('landingpage'), url_for('chamcong_industry', industry_code='kythuat'), url_for('quanly_kho'), url_for('quanly_dichvu')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateInvoice, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_hr.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_hr.html)
*   **Kích thước:** 101.05 KB (1431 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('register'), url_for('staff_list'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('landingpage'), url_for('bangluong')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateHrmPayroll, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_office.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_office.html)
*   **Kích thước:** 100.26 KB (1414 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong_fnb'), url_for('nhanvien'), url_for('register'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('quanly_thuchi'), url_for('landingpage'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `calculatePayroll, animate, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_retail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_retail.html)
*   **Kích thước:** 99.88 KB (1407 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('register'), url_for('baocao_loinhuan'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('sell'), url_for('landingpage'), url_for('quanly_kho')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, calculateRetailBill, formatCurrency`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [index.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/index.html)
*   **Kích thước:** 98.96 KB (1998 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/register` (app.py:351), `/login` (app.py:415), `/api/cskh/click` (app.py:614), `/api/cskh/feedback` (app.py:630), `/index.html` (app.py:669)
*   **Biến Jinja2 tiêu biểu:** `url_for('qr_menu_base'), url_for('customer_nurturing'), url_for('ai_bot'), url_for('register'), url_for('static', filename='css/tailwind.output.css'), session.get('user_email', 'BitPaw Merchant'), url_for('pos'), url_for('super_admin'), code, session.get('business_mode', 'retail')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `if, endwith, include, endfor, endif, elif, for, with`
*   **Các hàm JavaScript chính định nghĩa:** `showNextMessage, initEnhancedThree, showMessage, setLang, animate, closeFastCheckin, openFastCheckin, sendResetPassword, proceedToCamera, init3DHologramCore` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [ai-studio.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai-studio.html)
*   **Kích thước:** 93.5 KB (1231 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076)
*   **Biến Jinja2 tiêu biểu:** `url_for('ai_bot'), url_for('ai_studio'), url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('pos'), url_for('chamcong_industry', industry_code=active_industry_code), active_industry_code | default('retail')`
*   **Cấu trúc Jinja2 Control Flow:** `if, endif, else`
*   **Các hàm JavaScript chính định nghĩa:** `startDeepSeekRewrite, generateFacelessVideo, createNewProject, saveHistory, saveBrandBrain, generateKOCBrief, analyzeAlgorithm, closeMobileOptimizerModal, animate, generateLocalContent` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html)
*   **Kích thước:** 85.89 KB (1182 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127), `/map_dashboard` (app.py:2131), `/app_nhanvien` (app.py:2135)
*   **Các hàm JavaScript chính định nghĩa:** `initSignaturePad, deleteFromIndexedDB, startLiveTracking, toggleGPS, captureAndSubmit, dangXuat, sendSwapRequest, animate, vaoAppNgay, init3DBackground` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [crm_automation.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm_automation.html)
*   **Kích thước:** 81.13 KB (1228 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127)
*   **Biến Jinja2 tiêu biểu:** `url_for('nhanvien'), url_for('customers'), url_for('static', filename='css/tailwind.output.css'), url_for('quanly_dichvu')`
*   **Các hàm JavaScript chính định nghĩa:** `updateLivePreviewStyles, runScenarioTest, clearScenarioForm, saveScenarioFlow, toggleLogsView, sendLiveMessage, editScenarioFlow, toggleScenarioActiveStatus, loadCustomers, showToast` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [pos.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/pos.html)
*   **Kích thước:** 71.91 KB (1505 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/setup` (app.py:824), `/add` (app.py:842), `/update_product/<int:id>` (app.py:875), `/delete_product/<int:id>` (app.py:887), `/pos` (app.py:894)
*   **Biến Jinja2 tiêu biểu:** `session.get("business_id", ""), url_for('static', filename='css/tailwind.output.css'), url_for('index'), supabase_url, url_for('add_product'), supabase_key`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `initializeIndustryUI, loadAndRender, selectTable, trackCSKHClick, animate, loadTables, loadActiveTableOrders, init3D, renderTables, addOrderItem` *...và các hàm khác*
*   **Nợ kỹ thuật / Đoạn code dang dở:**
    *   *Dòng 1197:* `// Lưu các metadata tạm thời hỗ trợ in hóa đơn ở client`

### 📄 [payment_gateway.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_gateway.html)
*   **Kích thước:** 68.17 KB (1296 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595), `/inventory_alert` (app.py:1633), `/kitchen_display` (app.py:1637), `/ecommerce_sync` (app.py:1641), `/payment_gateway` (app.py:1645)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css'), url_for('index'), supabase_url, supabase_key, config | tojson | safe if config else 'null'`
*   **Các hàm JavaScript chính định nghĩa:** `populateFields, animate, updateQRPreview, switchTab, updateFieldsAndPreview, bindForceBtn, init3D, showLoading, showToast`
*   **Nợ kỹ thuật / Đoạn code dang dở:**
    *   *Dòng 876:* `// Bắt buộc log debug tạm trong console`

### 📄 [ai_bot.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ai_bot.html)
*   **Kích thước:** 66.02 KB (999 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000)
*   **Biến Jinja2 tiêu biểu:** `profile.email, url_for('ai_bot'), url_for('map_dashboard'), url_for('logout'), profile.tier, url_for('static', filename='css/tailwind.output.css'), url_for('ai_studio'), profile.name[0] | upper if profile.name else '?', profile.industry, url_for('index')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `if, endif, include, else`
*   **Các hàm JavaScript chính định nghĩa:** `renderEmptyState, showTypingIndicator, animate, appendUserMessageStatic, fetchCustomers, appendCopilotMessageStatic, renderCustomerList, appendAIMessageStatic, scrollToBottom, renderCampaignsList` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [omnichannel_connect.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect.html)
*   **Kích thước:** 63.86 KB (996 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127), `/map_dashboard` (app.py:2131), `/app_nhanvien` (app.py:2135), `/api/superadmin/duc_ma` (app.py:2139), `/api/superadmin/get_keys` (app.py:2154), `/omnichannel_connect` (app.py:2173)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, updateUIState, disconnectChannel, saveChannelConfig, runBootLog, clearLogs, logToConsole, triggerImport, closeConfigModal, testConnectionDirect` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [landing_nail.current_ai_bad_backup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing_nail.current_ai_bad_backup.html)
*   **Kích thước:** 58.05 KB (804 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('register'), url_for('chamcong_industry', industry_code='nail'), url_for('login'), url_for('static', filename='css/tailwind.output.css'), url_for('report'), url_for('landingpage'), url_for('public_booking'), url_for('quanly_dichvu')`
*   **Các hàm JavaScript chính định nghĩa:** `animate`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [super_admin.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/super_admin.html)
*   **Kích thước:** 57.76 KB (961 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `randomKey, animate, addLogLine, loadPaymentMethods, initEnhancedThree, init3DHologram, switchTab, xoaMa, animateHologram, initLiveLogsSimulator` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/dashboard.html)
*   **Kích thước:** 57.2 KB (800 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/dashboard` (app.py:702)
*   **Biến Jinja2 tiêu biểu:** `url_for('ai_bot'), url_for('map_dashboard'), url_for('logout'), url_for('ai_studio'), url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('pos'), url_for('chamcong_industry', industry_code=active_industry_code)`
*   **Cấu trúc Jinja2 Control Flow:** `if, endif, else`
*   **Các hàm JavaScript chính định nghĩa:** `googleTranslateElementInit, animateValue, animate, toggleCSKHChat, changeLanguage, loadKudoLeaderboard, initEnhancedThree, drawChart, sendCSKHMessage, updateClock` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/spa.html)
*   **Kích thước:** 57.08 KB (1431 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/update_promotion/<int:id>` (app.py:1106), `/delete_promotion/<int:id>` (app.py:1113), `/staff` (app.py:1120), `/add_staff` (app.py:1126), `/update_staff/<int:id>` (app.py:1139), `/delete_staff/<int:id>` (app.py:1146), `/customers` (app.py:1153), `/add_customer` (app.py:1166), `/update_customer/<int:id>` (app.py:1183), `/delete_customer/<int:id>` (app.py:1190), `/payment_transactions` (app.py:1197), `/update_payment_status/<int:id>` (app.py:1210), `/spa` (app.py:1218)
*   **Biến Jinja2 tiêu biểu:** `url_for('delete_spa', id=s.id), s.price, s.name, brand_color|default('#06b6d4', true), url_for('static', filename='uploads/spa_bg.jpg.webp'), url_for('static', filename='css/tailwind.output.css'), url_for('static', filename='uploads/' + s.image), url_for('brand_settings'), url_for('index'), url_for('add_spa')` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `if, endfor, endif, for, else`
*   **Các hàm JavaScript chính định nghĩa:** `adjustCart, updateCheckoutPriceDisplay, updatePaymentFormVisibility, updateCartUI, init3D, anim, formatCurrency, removeCartItem, filterGrid, showLoading` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_congnhan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_congnhan.html)
*   **Kích thước:** 54.53 KB (750 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877)
*   **Các hàm JavaScript chính định nghĩa:** `animate, submitFactory, closeKcsAlert, calcHours, backToList, checkKCS, loadWorkers, triggerConfetti, randomInRange, exportReport` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_nail.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_nail.html)
*   **Kích thước:** 52.65 KB (793 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, submitPos, exportSalary, backToList, loadWorkers, triggerConfetti, randomInRange, openPos, calculatePos, getFormattedDate` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_kythuat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_kythuat.html)
*   **Kích thước:** 52.36 KB (727 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892)
*   **Các hàm JavaScript chính định nghĩa:** `animate, autoSuggestMaterials, backToList, loadWorkers, triggerConfetti, randomInRange, closePhoto, openPos, submitTech, viewPhoto` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [map_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/map_dashboard.html)
*   **Kích thước:** 51.88 KB (838 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127), `/map_dashboard` (app.py:2131)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `showAIAlert, animate, fetchWorkers, setupRealtime, applyFilter, checkAuth, closeManualJobModal, kichHoatBotAI, fetchInitialData, kichHoatAIDieuPhoi` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_fnb.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_fnb.html)
*   **Kích thước:** 51.63 KB (746 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882)
*   **Các hàm JavaScript chính định nghĩa:** `animate, chiaDeuTips, calcHours, backToList, loadWorkers, triggerConfetti, randomInRange, exportReport, openPos, submitFnb` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [table_order.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/table_order.html)
*   **Kích thước:** 46.89 KB (982 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ✅ Có
*   **Được render bởi Route:** `/update_product/<int:id>` (app.py:875), `/delete_product/<int:id>` (app.py:887), `/pos` (app.py:894), `/add_table` (app.py:942), `/table/<int:table_id>` (app.py:954), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920)
*   **Biến Jinja2 tiêu biểu:** `table.name, url_for('static', filename='css/tailwind.output.css'), table.id`
*   **Các hàm JavaScript chính định nghĩa:** `attachProductEvents, initSidebar, init, updateUIAfterLang, initCSKH, loadTableInfo, renderCart, init3D, animate, initLanguage` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [bangluong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/bangluong.html)
*   **Kích thước:** 46.25 KB (696 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868)
*   **Các hàm JavaScript chính định nghĩa:** `setupDynamicHeaders, closeTipsModal, animate, loadBangLuong, formatMoney, openTipsModal, toggleCSKHChat, sendCSKHMessage, toggleCurrency, triggerConfetti` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_spa.html)
*   **Kích thước:** 46.25 KB (689 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902)
*   **Các hàm JavaScript chính định nghĩa:** `fireConfetti, renderVongQuayTua, animateBg, saveVipProfile, renderTable, switchTab, closeModal, previewImage, openModal, loadSpa` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chat.html)
*   **Kích thước:** 45.32 KB (739 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `fetchUserInfo, animate, togglePopup, checkAuth, createMessageElement, sendGif, insertText, hideAllPopups, renderOnlineUsers, scrollToBottom` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/nhanvien.html)
*   **Kích thước:** 44.84 KB (672 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864)
*   **Các hàm JavaScript chính định nghĩa:** `unformat, viewHistory, filterDept, saveSalary, deleteEmployee, nextPage, formatCurrency, init3D, animate, renderTable` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [payment_success.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_success.html)
*   **Kích thước:** 44.7 KB (888 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('pos'), supabase_url, supabase_key`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, createConfetti, escapeHtml, init3D, showLoading, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [admin_payment_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/admin_payment_management.html)
*   **Kích thước:** 44.22 KB (923 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/promotions` (app.py:1077), `/add_promotion` (app.py:1088), `/update_promotion/<int:id>` (app.py:1106), `/delete_promotion/<int:id>` (app.py:1113), `/staff` (app.py:1120), `/add_staff` (app.py:1126), `/update_staff/<int:id>` (app.py:1139), `/delete_staff/<int:id>` (app.py:1146), `/customers` (app.py:1153), `/add_customer` (app.py:1166), `/update_customer/<int:id>` (app.py:1183), `/delete_customer/<int:id>` (app.py:1190), `/payment_transactions` (app.py:1197)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('payment_gateway'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `updateStatsAndCharts, loadTransactions, showDetailModal, resetFilters, trackCSKHClick, animate, getStatusBadge, renderTable, closeModal, updateTransactionStatus` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [qr_menu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/qr_menu.html)
*   **Kích thước:** 44.13 KB (934 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ✅ Có
*   **Được render bởi Route:** `/user_logs` (app.py:1425), `/backup_restore` (app.py:1433), `/api/backup/create` (app.py:1438), `/api/backup/restore` (app.py:1471), `/api/backup/list` (app.py:1487), `/qr_menu` (app.py:1500), `/qr_menu/<path:identifier>` (app.py:1505)
*   **Biến Jinja2 tiêu biểu:** `table.name, url_for('static', filename='css/tailwind.output.css'), table.id`
*   **Các hàm JavaScript chính định nghĩa:** `attachProductEvents, trackCSKHClick, initSidebar, init, updateUIAfterLang, initCSKH, loadTableInfo, renderCart, init3D, animate` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [ad_assistant.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ad_assistant.html)
*   **Kích thước:** 42.89 KB (963 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/` (ad_assistant.py:95)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, fetchSuggestions, trackCSKHClick, updateChart, parseMessage, autoFillFormAndFetch, updateLivePreview, addMessage, renderSuggestions, escapeHtml` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [quanly_dichvu.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_dichvu.html)
*   **Kích thước:** 42.28 KB (617 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `drag, dragEnd, openJobModal, deleteDichVu, confirmAssign, addDichVu, loadDichVu, cancelAssign, leaveDrop, showToast` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [promotion_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/promotion_management.html)
*   **Kích thước:** 42.21 KB (658 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/order_item/<int:table_id>` (app.py:979), `/checkout/<int:table_id>` (app.py:993), `/add_expense` (app.py:1032), `/expense_list` (app.py:1060), `/promotions` (app.py:1077)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `resetFilters, deletePromotion, trackCSKHClick, updateChart, loadPromotions, openAddModal, openEditModal, init3D, animate, openDeleteModal` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [report.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/report.html)
*   **Kích thước:** 41.78 KB (893 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/checkout_spa` (app.py:1268), `/booking/service/<service_id>` (app.py:1295), `/create_appointment` (app.py:1301), `/karaoke` (app.py:1316), `/toggle_room/<int:room_id>` (app.py:1322), `/report` (app.py:1363)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, showToastMsg, updateDashboard, exportToExcel, fetchReportData, escapeHtml, init3D, showLoading`
*   **Nợ kỹ thuật / Đoạn code dang dở:**
    *   *Dòng 542:* `// Tính doanh thu ước lượng (cần giá bán từ products, nhưng tạm thời bỏ qua revenue)`

### 📄 [chamcong_khachsan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_khachsan.html)
*   **Kích thước:** 39.71 KB (574 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887)
*   **Các hàm JavaScript chính định nghĩa:** `animate, checkoutRoom, saveHotel, loadHotel, assignCleaning, triggerConfetti, randomInRange, renderRooms, init3D, showToast` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [quanly_congno.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_congno.html)
*   **Kích thước:** 38.49 KB (644 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('static', filename='js/chart.min.js'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `saveTransaction, animate, closeTransactionModal, loadDebtList, toggleCustomerSupplier, openTransactionModal, openTransactionModalWithPartner, exportToExcel, viewDetail, closeDetailModal` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [staff_management.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/staff_management.html)
*   **Kích thước:** 38.44 KB (898 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/add_expense` (app.py:1032), `/expense_list` (app.py:1060), `/promotions` (app.py:1077), `/add_promotion` (app.py:1088), `/update_promotion/<int:id>` (app.py:1106), `/delete_promotion/<int:id>` (app.py:1113), `/staff` (app.py:1120)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `renderStaffTable, trackCSKHClick, openAddModal, openEditModal, init3D, loadStaff, sendSupportRequest, animate, openDeleteModal, confirmDelete` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [profit_by_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/profit_by_product.html)
*   **Kích thước:** 38.3 KB (613 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/karaoke` (app.py:1316), `/toggle_room/<int:room_id>` (app.py:1322), `/report` (app.py:1363), `/profit_report` (app.py:1390)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `resetFilters, trackCSKHClick, formatCurrency, init3D, loadProfitData, animate, renderTable, applyFilters, showToast, openCostModal` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [customer_nurturing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/customer_nurturing.html)
*   **Kích thước:** 38.1 KB (602 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127), `/map_dashboard` (app.py:2131), `/app_nhanvien` (app.py:2135), `/api/superadmin/duc_ma` (app.py:2139), `/api/superadmin/get_keys` (app.py:2154), `/omnichannel_connect` (app.py:2173), `/customer_nurturing` (app.py:2178)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `syncPOSData, animate, fetchCustomers, copyAISuggest, runBootLog, renderCustomers, filterCustomers, generateAISuggestReply, momentOffsetDate, init3D` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [add_expense.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_expense.html)
*   **Kích thước:** 37.98 KB (738 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/table/<int:table_id>` (app.py:954), `/order_item/<int:table_id>` (app.py:979), `/checkout/<int:table_id>` (app.py:993), `/add_expense` (app.py:1032)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css'), url_for('expense_list')`
*   **Các hàm JavaScript chính định nghĩa:** `formatNumberInput, animate, trackCSKHClick, loadExpenseData, updateAuthUI, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [quanly_thuchi.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_thuchi.html)
*   **Kích thước:** 37.05 KB (619 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('static', filename='js/chart.min.js'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `saveTransaction, animate, loadTransactions, closeTransactionModal, drawChart, toggleCategory, openTransactionModal, deleteTransaction, exportToExcel, editTransaction` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [crm.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/crm.html)
*   **Kích thước:** 36.73 KB (481 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/add_expense` (app.py:1032), `/expense_list` (app.py:1060), `/promotions` (app.py:1077), `/add_promotion` (app.py:1088), `/update_promotion/<int:id>` (app.py:1106), `/delete_promotion/<int:id>` (app.py:1113), `/staff` (app.py:1120), `/add_staff` (app.py:1126), `/update_staff/<int:id>` (app.py:1139), `/delete_staff/<int:id>` (app.py:1146), `/customers` (app.py:1153)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `animate, resetFilters, trackCSKHClick, renderTable, showDetail, escapeHtml, updateStatsAndChart, getTierBadge, openAddModal, exportToExcel` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [payment_history.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_history.html)
*   **Kích thước:** 36.53 KB (774 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595), `/inventory_alert` (app.py:1633), `/kitchen_display` (app.py:1637), `/ecommerce_sync` (app.py:1641), `/payment_gateway` (app.py:1645), `/api/payment/save_config` (app.py:1659), `/payment_history` (app.py:1687)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('payment_gateway'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `loadTransactions, showDetailModal, resetFilters, trackCSKHClick, animate, getStatusBadge, renderTable, closeModal, updateCharts, formatCurrency` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [inventory_alert.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/inventory_alert.html)
*   **Kích thước:** 36.51 KB (531 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595), `/inventory_alert` (app.py:1633)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, resetFilters, trackCSKHClick, getStatusBadge, updateChart, renderTable, restockProduct, updateStats, exportToExcel, loadProducts` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong_vanphong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong_vanphong.html)
*   **Kích thước:** 35.76 KB (547 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907)
*   **Các hàm JavaScript chính định nghĩa:** `loadOffice, animateBg, markAllPresent, frame, fireConfettiSide, renderKudoBoard, saveRow, duyetNghiPhep, showToast, raf`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [backup_restore.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/backup_restore.html)
*   **Kích thước:** 35.53 KB (593 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/report` (app.py:1363), `/profit_report` (app.py:1390), `/user_logs` (app.py:1425), `/backup_restore` (app.py:1433)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `openConfirmModal, animate, trackCSKHClick, restoreFromCloud, loadCloudBackups, init, uploadBackupToCloud, closeConfirmModal, fetchAllData, restoreAllData` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [user_logs.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/user_logs.html)
*   **Kích thước:** 32.59 KB (520 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/toggle_room/<int:room_id>` (app.py:1322), `/report` (app.py:1363), `/profit_report` (app.py:1390), `/user_logs` (app.py:1425)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `updateHourlyChart, sendSupportRequest, animate, resetFilters, trackCSKHClick, renderTable, getActionBadge, updateStats, exportToExcel, applyFilters` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [brand_settings.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/brand_settings.html)
*   **Kích thước:** 32.53 KB (628 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595)
*   **Biến Jinja2 tiêu biểu:** `url_for('spa'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, saveSettings, updatePreview, loadSettings, init3D, showToast, uploadFile`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [campaign_builder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/campaign_builder.html)
*   **Kích thước:** 32.5 KB (523 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119), `/chat` (app.py:2123), `/crm_automation` (app.py:2127), `/map_dashboard` (app.py:2131), `/app_nhanvien` (app.py:2135), `/api/superadmin/duc_ma` (app.py:2139), `/api/superadmin/get_keys` (app.py:2154), `/omnichannel_connect` (app.py:2173), `/customer_nurturing` (app.py:2178), `/campaign_builder` (app.py:2183)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `fetchApprovalQueue, animate, renderApprovalQueue, runBootLog, previewMessage, approveMessage, createCampaign, init3D`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [baocao_loinhuan.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/baocao_loinhuan.html)
*   **Kích thước:** 32.21 KB (551 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong'), url_for('nhanvien'), url_for('quanly_congno'), url_for('static', filename='css/tailwind.output.css'), url_for('chat'), url_for('quanly_thuchi'), url_for('home'), url_for('static', filename='js/chart.min.js'), url_for('bangluong'), url_for('baocao_loinhuan')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, loadProfitReport, drawChart, exportToExcel, exportToPDF, changePeriodType, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [portal.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/portal.html)
*   **Kích thước:** 31.98 KB (654 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Cấu trúc Jinja2 Control Flow:** `include`
*   **Các hàm JavaScript chính định nghĩa:** `sendMedia, init3D, animate, applyHumanTypo, appendMessage, sendMultipleMessages, scrollToBottom, getAIResponse, subscribeToRealtime, loadHistory` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [checkout.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/checkout.html)
*   **Kích thước:** 30.37 KB (473 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/landing` (app.py:798), `/checkout` (app.py:803)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `fireConfetti, animateBg, processOrder, generateQR, frame, fetchPaymentMethods, raf`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [app_chat.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_chat.html)
*   **Kích thước:** 30.32 KB (475 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987), `/quanly_thuchi` (app.py:1991), `/super-admin` (app.py:1996), `/ai_bot` (app.py:2000), `/ai_studio` (app.py:2076), `/api/ai/studio/generate` (app.py:2080), `/app_chat` (app.py:2119)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, uploadImage, loadDanhBa, init3DBackground, setupRealtime, closeChat, renderMessage, closeLightbox, openChat, getChatRoomId` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [karaoke.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/karaoke.html)
*   **Kích thước:** 29.95 KB (680 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/payment_transactions` (app.py:1197), `/update_payment_status/<int:id>` (app.py:1210), `/spa` (app.py:1218), `/add_spa` (app.py:1241), `/delete_spa/<int:id>` (app.py:1262), `/checkout_spa` (app.py:1268), `/booking/service/<service_id>` (app.py:1295), `/create_appointment` (app.py:1301), `/karaoke` (app.py:1316)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, startTimers, loadRooms, attachEvents, startRoom, escapeHtml, renderRooms, init3D, showLoading` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [ecommerce_sync.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/ecommerce_sync.html)
*   **Kích thước:** 29.87 KB (431 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595), `/inventory_alert` (app.py:1633), `/kitchen_display` (app.py:1637), `/ecommerce_sync` (app.py:1641)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='js/chart.min.js'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `syncAll, animate, loadSyncData, trackCSKHClick, addLog, saveConnection, init3D, showLoading, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [sell.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/sell.html)
*   **Kích thước:** 29.28 KB (674 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, loadProduct, createOrder, updateTotalPreview, showToastMessage, init3D, showLoading`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [login.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/login.html)
*   **Kích thước:** 28.83 KB (630 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `message, url_for('login'), url_for('register'), url_for('static', filename='css/tailwind.output.css')`
*   **Cấu trúc Jinja2 Control Flow:** `if, endwith, endfor, endif, elif, for, with, else`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, saveCredentials, loadSavedCredentials, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [chamcong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/chamcong.html)
*   **Kích thước:** 28.63 KB (388 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/confirm` (app.py:1756), `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912)
*   **Các hàm JavaScript chính định nghĩa:** `toggleCSKHChat, animate, checkAuth, sendCSKHMessage, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [kitchen_display.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/kitchen_display.html)
*   **Kích thước:** 28.52 KB (645 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/brand_settings` (app.py:1595), `/inventory_alert` (app.py:1633), `/kitchen_display` (app.py:1637)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, connectRealtime, showToast, renderOrders, checkNewOrders, demoAddOrder, escapeHtml, init3D, showLoading` *...và các hàm khác*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [add_product.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_product.html)
*   **Kích thước:** 26.34 KB (537 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/landing` (app.py:798), `/checkout` (app.py:803), `/landing_nail` (app.py:808), `/solutions/<industry_code>` (app.py:813), `/setup` (app.py:824), `/add` (app.py:842)
*   **Biến Jinja2 tiêu biểu:** `url_for('index'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `uploadImage, animate, formatPriceInput, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [fnb_dashboard.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/fnb_dashboard.html)
*   **Kích thước:** 26.23 KB (607 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971)
*   **Biến Jinja2 tiêu biểu:** `url_for('setup'), url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('karaoke'), url_for('report'), url_for('pos'), url_for('spa')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, trackCSKHClick, showComingSoonModal, hideComingSoonModal, init3D, showLoading, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [add_spa.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/add_spa.html)
*   **Kích thước:** 26.08 KB (538 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/update_staff/<int:id>` (app.py:1139), `/delete_staff/<int:id>` (app.py:1146), `/customers` (app.py:1153), `/add_customer` (app.py:1166), `/update_customer/<int:id>` (app.py:1183), `/delete_customer/<int:id>` (app.py:1190), `/payment_transactions` (app.py:1197), `/update_payment_status/<int:id>` (app.py:1210), `/spa` (app.py:1218), `/add_spa` (app.py:1241)
*   **Biến Jinja2 tiêu biểu:** `url_for('spa'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `uploadImage, animate, trackCSKHClick, formatPriceInput, init3D, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/register.html)
*   **Kích thước:** 26.0 KB (549 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Biến Jinja2 tiêu biểu:** `url_for('register'), cfg.name, url_for('static', filename='css/tailwind.output.css'), url_for('login'), message, cfg.icon, code`
*   **Cấu trúc Jinja2 Control Flow:** `if, endwith, endfor, endif, elif, for, with, else`
*   **Các hàm JavaScript chính định nghĩa:** `animate, init3D, trackCSKHClick, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [setup.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/setup.html)
*   **Kích thước:** 25.98 KB (623 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/landing` (app.py:798), `/checkout` (app.py:803), `/landing_nail` (app.py:808), `/solutions/<industry_code>` (app.py:813), `/setup` (app.py:824)
*   **Biến Jinja2 tiêu biểu:** `cfg.desc|default(''), url_for('setup'), cfg.name, url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('karaoke'), url_for('pos'), cfg.icon|default('💼'), code, url_for('spa')`
*   **Cấu trúc Jinja2 Control Flow:** `for, endfor`
*   **Các hàm JavaScript chính định nghĩa:** `openConfirmModal, animate, trackCSKHClick, closeConfirmModal, showToastMessage, saveBusinessMode, init3D, showLoading, clearSelected`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [booking.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/booking.html)
*   **Kích thước:** 24.18 KB (424 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/update_customer/<int:id>` (app.py:1183), `/delete_customer/<int:id>` (app.py:1190), `/payment_transactions` (app.py:1197), `/update_payment_status/<int:id>` (app.py:1210), `/spa` (app.py:1218), `/add_spa` (app.py:1241), `/delete_spa/<int:id>` (app.py:1262), `/checkout_spa` (app.py:1268), `/booking/service/<service_id>` (app.py:1295)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `animate, init3DBackground, loadServices, randomInRange, triggerConfetti, showSuccessScreen, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [payment_pending.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/payment_pending.html)
*   **Kích thước:** 24.04 KB (454 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/inventory_alert` (app.py:1633), `/kitchen_display` (app.py:1637), `/ecommerce_sync` (app.py:1641), `/payment_gateway` (app.py:1645), `/api/payment/save_config` (app.py:1659), `/payment_history` (app.py:1687), `/payment_pending` (app.py:1691)
*   **Biến Jinja2 tiêu biểu:** `config.account_number, config.provider_name, config.transfer_prefix, config.business_name, config.account_holder, config.bank_name, url_for('static', filename='css/tailwind.output.css'), config.intl_email_account, config.bank_code, config.device_name or 'Default Counter'` *...và các biến khác*
*   **Cấu trúc Jinja2 Control Flow:** `if, endif, elif, else`
*   **Các hàm JavaScript chính định nghĩa:** `animate, init3D, showLoading, showToast`
*   **Nợ kỹ thuật / Đoạn code dang dở:**
    *   *Dòng 403:* `showToast('🔴 Đã hủy giao dịch tạm thời. Quay lại POS...');`

### 📄 [quanly_kho.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/quanly_kho.html)
*   **Kích thước:** 23.21 KB (393 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967), `/fnb_dashboard` (app.py:1971), `/portal` (app.py:1975), `/quanly_congno` (app.py:1979), `/quanly_dichvu` (app.py:1983), `/quanly_kho` (app.py:1987)
*   **Biến Jinja2 tiêu biểu:** `url_for('chamcong_industry', industry_code='kythuat'), url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `setFilter, animateBg, loadDataKho, renderKho, deleteItem, resetForm, editItem, exportToCSV`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [cauhinh_luong.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/cauhinh_luong.html)
*   **Kích thước:** 22.39 KB (375 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951)
*   **Biến Jinja2 tiêu biểu:** `emp[2], url_for('static', filename='css/tailwind.output.css'), emp[0], emp[1]`
*   **Các hàm JavaScript chính định nghĩa:** `animate, init3DBackground, toggleSalaryFields, randomInRange, triggerConfetti, saveConfig, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [expense_list.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/expense_list.html)
*   **Kích thước:** 16.0 KB (336 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/order_item/<int:table_id>` (app.py:979), `/checkout/<int:table_id>` (app.py:993), `/add_expense` (app.py:1032), `/expense_list` (app.py:1060)
*   **Biến Jinja2 tiêu biểu:** `e.description|lower, e.description, url_for('static', filename='css/tailwind.output.css'), url_for('index'), url_for('add_expense'), e.expense_date, e.category`
*   **Cấu trúc Jinja2 Control Flow:** `if, endfor, endif, for, else`
*   **Các hàm JavaScript chính định nghĩa:** `filterExpenses, init3D, animate, showToast`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [diemdanh.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/diemdanh.html)
*   **Kích thước:** 14.98 KB (269 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/payment/cancel` (app.py:1834), `/payment_success` (app.py:1855), `/sell` (app.py:1859), `/nhanvien` (app.py:1864), `/bangluong` (app.py:1868), `/chamcong` (app.py:1872), `/chamcong_congnhan` (app.py:1877), `/chamcong_fnb` (app.py:1882), `/chamcong_khachsan` (app.py:1887), `/chamcong_kythuat` (app.py:1892), `/chamcong_nail` (app.py:1897), `/chamcong_spa` (app.py:1902), `/chamcong_vanphong` (app.py:1907), `/chamcong_<industry_code>` (app.py:1912), `/table_order` (app.py:1920), `/baocao_loinhuan` (app.py:1947), `/cauhinh_luong` (app.py:1951), `/diemdanh` (app.py:1967)
*   **Biến Jinja2 tiêu biểu:** `url_for('static', filename='css/tailwind.output.css')`
*   **Các hàm JavaScript chính định nghĩa:** `cancelCheckin, captureAndSubmit, startCameraAndGPS, updateClock`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [omnichannel_connect_placeholder.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/omnichannel_connect_placeholder.html)
*   **Kích thước:** 10.67 KB (207 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** `/api/ai/nurture/test-connection` (app.py:2329), `/omnichannel/status` (app.py:2363), `/omnichannel/status/<channel>` (app.py:2367), `/omnichannel/connect/<channel>` (app.py:2379)
*   **Biến Jinja2 tiêu biểu:** `channel.upper(), channel, url_for('static', filename='css/tailwind.output.css')`
*   **Cấu trúc Jinja2 Control Flow:** `if, endif, elif, else`
*   **Các hàm JavaScript chính định nghĩa:** `animate, autoFill`
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 

### 📄 [components/cskh_global.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/components/cskh_global.html)
*   **Kích thước:** 3.56 KB (53 dòng)
*   **Hỗ trợ đa ngôn ngữ (data-i18n):** ❌ Không
*   **Được render bởi Route:** *Không tìm thấy trực tiếp (Có thể được load động hoặc thông qua AJAX)*
*   **Nợ kỹ thuật:** `Không phát hiện ghi chú TODO/FIXME` 


---

## 3. TỔNG HỢP NỢ KỸ THUẬT & ĐỀ XUẤT CỦA TECH LEAD

### A. Đồng bộ Đa ngôn ngữ (Client-side JS Translation)
*   **Vấn đề:** Hiện tại chỉ có [landing.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/landing.html) và một số ít file có cơ chế dịch ngôn ngữ thông qua thẻ `data-i18n` và dictionary `translations` trong JS. Trạng thái ngôn ngữ bị mất khi F5 (chưa lưu vào LocalStorage/Cookie).
*   **Khắc phục:** Viết một script toàn cục lưu trong `static/js/i18n.js` để tự động đọc/ghi ngôn ngữ vào `localStorage` và áp dụng hàm dịch khi tải trang.
*   **Phạm vi:** 90% các trang landing ngành dọc (`landing_spa.html`, `landing_fnb.html`...) và trang dashboard nghiệp vụ hoàn toàn chưa dịch.

### B. Technical Debt phình to của file app.py
*   **Vấn đề:** File `app.py` có kích thước gần 150KB, chứa hầu hết các hàm xử lý API và định tuyến.
*   **Khắc phục:** Tách thành các file blueprint độc lập tương tự như `ad_assistant.py` và `ad_suggest_api.py`. Gợi ý chia nhỏ thành:
    1.  `auth_routes.py` (Đăng nhập, đăng ký, cấp license)
    2.  `hrm_routes.py` (Chấm công, tính lương, quản lý nhân viên)
    3.  `pos_routes.py` (Bán hàng, order bàn, kitchen display)
    4.  `finance_routes.py` (Thu chi, công nợ, lợi nhuận)
    5.  `ai_routes.py` (AI Studio, CSKH request, AI Nurture)

### C. Quản lý trạng thái Supabase/SQLite kép
*   **Vấn đề:** Chưa có cơ chế đồng bộ ngược dữ liệu (Data sync logic) từ SQLite local lên Supabase khi máy chủ mất kết nối và kết nối lại. Lập trình viên mới cần viết thêm một worker ngầm kiểm tra kết nối định kỳ và thực thi đồng bộ dữ liệu.
