# ========================================================================================
# MODULE NGÀNH RETAIL (Bán lẻ) — theo kiến trúc "1 ngành = 1 file" (xem blueprints/spa_bp.py
# để biết lý do dùng @app.route thẳng thay vì flask.Blueprint).
#
# Trước khi có file này, ngành Retail KHÔNG có màn hình bán hàng thật: dashboard_route trỏ vào
# /dashboard (dashboard.html) — template đó chỉ hiển thị Tasks/Leaderboard/Reconciliation, hoàn
# toàn không có danh sách sản phẩm hay nút bán hàng nào (biến `products` mà index() truyền vào
# không được dashboard.html dùng ở đâu cả). Link "Bán hàng" duy nhất trong sidebar trỏ vào /sell
# — nhưng /sell không có ?product_id= sẽ redirect thẳng về index(), tạo vòng lặp chết. Route
# /retail_pos ở đây là màn POS thật đầu tiên cho ngành Retail: lưới sản phẩm + giỏ hàng nhiều
# món + quét mã vạch, cùng mẫu với /spa (spa_bp.py) và pos_nail.html.
# ========================================================================================

from flask import render_template, session

from mongo_client import db
from app import app, login_required, _brand_setting_get


@app.route('/retail_pos')
@login_required
def retail_pos():
    business_id = session.get('business_id') or session['user_id']
    try:
        brand_name = _brand_setting_get(business_id, 'brand_name', 'BitPaw')
    except Exception as db_err:
        print(f"MongoDB brand_name select failed: {str(db_err)}")
        brand_name = 'BitPaw'
    try:
        brand_color = _brand_setting_get(business_id, 'brand_color', '#6366f1')
    except Exception as db_err:
        print(f"MongoDB brand_color select failed: {str(db_err)}")
        brand_color = '#6366f1'
    try:
        products_data = list(db.products.find(
            {'is_active': 1, 'channel_type': 'retail', 'business_id': business_id}, {'_id': 0}
        ).sort('name', 1))
    except Exception as db_err:
        print(f"MongoDB products select failed: {str(db_err)}")
        products_data = []
    return render_template(
        'retail_pos.html', products=products_data, brand_name=brand_name, brand_color=brand_color
    )
