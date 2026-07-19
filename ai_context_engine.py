from mongo_client import db, MONGO_STATUS

class AIContextEngine:
    @staticmethod
    def _load_purchase_history(business_id, customer_phone, limit=5):
        """Trí nhớ dài hạn: các lần mua hàng/dùng dịch vụ gần nhất của ĐÚNG khách này
        (không phải tổng doanh thu chung), để AI biết khách từng mua gì, khi nào.
        Dùng $lookup nối order_items -> products ngay trong 1 aggregation, tương đương
        embedded-join "products(name, category)" của Postgres/PostgREST cũ."""
        if MONGO_STATUS != "CONNECTED" or not business_id or not customer_phone:
            return []
        try:
            pipeline = [
                {'$match': {'business_id': business_id, 'customer_phone': customer_phone}},
                {'$sort': {'created_at': -1}},
                {'$limit': limit},
                {'$lookup': {'from': 'products', 'localField': 'product_id', 'foreignField': 'id', 'as': '_product'}},
                {'$addFields': {'products': {'$arrayElemAt': [{'$map': {
                    'input': '_product', 'as': 'p', 'in': {'name': '$$p.name', 'category': '$$p.category'}
                }}, 0]}}},
                {'$project': {'quantity': 1, 'total_price': 1, 'created_at': 1, 'products': 1, '_id': 0}}
            ]
            return list(db.order_items.aggregate(pipeline))
        except Exception:
            return []

    @staticmethod
    def _load_recent_service_photos(business_id, customer_phone, limit=3):
        """Ảnh mẫu dịch vụ cũ (vd: mẫu nail đã làm tháng trước) của ĐÚNG khách này,
        để AI có thể nhắc lại/gợi ý làm lại khi khách quay lại chat."""
        if MONGO_STATUS != "CONNECTED" or not business_id or not customer_phone:
            return []
        try:
            return list(
                db.service_photos.find(
                    {'business_id': business_id, 'customer_phone': customer_phone},
                    {'image_url': 1, 'note': 1, 'created_at': 1, '_id': 0}
                ).sort('created_at', -1).limit(limit)
            )
        except Exception:
            return []

    @staticmethod
    def build_context_prompt(business_id, industry_code, customer_phone=None, include_private_data=True):
        """Constructs an intelligent, tenant-aware system prompt.

        Đa doanh nghiệp (multi-tenant): tra business_id ra ĐÚNG tên cửa hàng, danh mục
        sản phẩm/dịch vụ và bảng giá thật của tenant đó, không fix cứng kịch bản cho
        bất kỳ ngành nào. Nếu không có business_id (vd: bot tư vấn marketing chung của
        BitPaw trên trang landing), trả về persona chung theo industry_code như cũ.

        include_private_data: chỉ True khi caller đã xác thực (session đăng nhập) và
        business_id đến từ session đó. Khi False (khách ẩn danh gọi widget công khai,
        business_id do client tự khai), TUYỆT ĐỐI không nhúng doanh thu hay thông tin
        khách hàng (PII, hạng thành viên, lịch sử mua hàng, ảnh mẫu dịch vụ) vào prompt
        — chỉ được phép nhúng dữ liệu công khai (tên cửa hàng, bảng giá/danh mục dịch vụ).

        Returns: {"prompt": str, "business_name": str|None}
        """
        base_prompt = "Bạn là trợ lý AI CSKH của BitPaw OS."

        industry_prompts = {
            "retail": "Bạn là chuyên gia tư vấn bán lẻ tối ưu hóa dòng sản phẩm, chiến dịch quảng cáo và thanh lý hàng tồn kho.",
            "fnb": "Bạn là chuyên gia vận hành F&B giúp sơ đồ bàn ăn thông suốt, tối ưu hóa thực đơn món ăn gọi món và tốc độ bếp.",
            "spa": "Bạn là quản trị viên Spa chuyên nghiệp giúp điều phối lịch hẹn kỹ thuật viên và thúc đẩy doanh thu bán liệu trình.",
            "nail": "Bạn là chuyên gia tư vấn Nails & Salon tối ưu hóa chất lượng thợ nail nghệ thuật.",
            "karaoke": "Bạn là quản trị viên Karaoke bida giúp tối ưu hóa công suất phòng hát, giờ vàng bida giải trí.",
            "hotel": "Bạn là lễ tân Homestay giúp sơ đồ buồng phòng check-in check-out hoàn hảo.",
            "production": "Bạn là tổ trưởng xưởng sản xuất giúp công nhân đạt năng suất kíp xưởng tối đa.",
            "technical": "Bạn là điều phối viên kỹ thuật viên thực địa hiện trường qua định vị GPS.",
            "office": "Bạn là thư ký hành chính tối ưu hóa bảng chấm công và tính toán bảng lương."
        }

        # Tra tên cửa hàng thật + industry_code chính thức của tenant (nếu có business_id thật)
        business_name = None
        if MONGO_STATUS == "CONNECTED" and business_id:
            try:
                biz = db.businesses.find_one({'id': business_id}, {'name': 1, 'industry_code': 1, '_id': 0})
                if biz:
                    business_name = biz.get('name') or None
                    industry_code = industry_code or biz.get('industry_code')
            except:
                pass

        if not industry_code:
            return {"prompt": base_prompt, "business_name": business_name}

        custom_prompt = industry_prompts.get(industry_code.lower(), "Bạn là chuyên gia tư vấn tăng trưởng.")

        # Load business metrics if connected — dữ liệu nhạy cảm, chỉ nhúng khi caller đã xác thực.
        revenue_sum = 0
        if include_private_data and MONGO_STATUS == "CONNECTED" and business_id:
            try:
                orders_data = list(db.orders.find({'business_id': business_id}, {'total_amount': 1, '_id': 0}))
                revenue_sum = sum(o.get('total_amount') or 0 for o in orders_data)
            except:
                pass

        details = f"\n- Ngành nghề: {industry_code.upper()}\n- Quy mô: SaaS Enterprise"
        if include_private_data:
            details += f"\n- Báo cáo doanh thu hiện tại: {revenue_sum} VNĐ."

        # Nhúng menu/sản phẩm thật của tenant để AI gợi ý upsell/cross-sell đúng mặt hàng đang bán,
        # không bịa ra sản phẩm không tồn tại.
        menu_snippet = ""
        has_catalog = False
        if MONGO_STATUS == "CONNECTED" and business_id:
            try:
                prods = list(db.products.find(
                    {'business_id': business_id, 'is_active': 1}, {'name': 1, 'price': 1, 'category': 1, '_id': 0}
                ).limit(40))
                if prods:
                    has_catalog = True
                    lines = [
                        f"- {p.get('name')} ({p.get('category') or 'khác'}): {int(p.get('price') or 0):,}đ".replace(',', '.')
                        for p in prods
                    ]
                    menu_snippet = (
                        "\n\nBẢNG GIÁ & DANH MỤC SẢN PHẨM/DỊCH VỤ ĐANG BÁN THẬT (chỉ được tư vấn/gợi ý đúng các "
                        "món và mức giá dưới đây, tuyệt đối không bịa thêm sản phẩm hoặc mức giá không có trong danh sách):\n"
                        + "\n".join(lines)
                    )
            except:
                pass

        # Nhúng thông tin khách hàng (hạng thành viên, tổng chi tiêu = proxy cho lịch sử mua hàng)
        # nếu tra được theo SĐT, để AI cá nhân hoá lời tư vấn và ưu tiên gợi ý xứng tầm khách VIP.
        # PII/lịch sử mua hàng chỉ được nhúng khi caller đã xác thực (include_private_data=True) —
        # khách ẩn danh gọi widget công khai tuyệt đối không được thấy dữ liệu này.
        customer_snippet = ""
        if include_private_data and MONGO_STATUS == "CONNECTED" and business_id and customer_phone:
            try:
                c = db.customers.find_one(
                    {'business_id': business_id, 'phone': customer_phone},
                    {'name': 1, 'tier': 1, 'loyalty_points': 1, 'total_spent': 1, '_id': 0}
                )
                if c:
                    spent = int(c.get('total_spent') or 0)
                    customer_snippet = (
                        f"\n\nTHÔNG TIN KHÁCH ĐANG CHAT: Tên {c.get('name') or 'chưa rõ'}, "
                        f"Hạng thành viên: {c.get('tier') or 'Normal'}, Điểm tích luỹ: {c.get('loyalty_points') or 0}, "
                        f"Tổng chi tiêu từ trước tới nay: {spent:,}đ (dùng số này như lịch sử mua hàng để đánh giá gu/khả năng chi trả)."
                        .replace(',', '.')
                    )
            except:
                pass

            # Trí nhớ dài hạn: lần mua gần nhất + ảnh mẫu dịch vụ cũ, để AI tư vấn/chốt sale
            # cá nhân hoá đúng gu khách thay vì tư vấn chung chung.
            history = AIContextEngine._load_purchase_history(business_id, customer_phone)
            if history:
                lines = []
                for h in history:
                    prod = h.get('products') or {}
                    name = prod.get('name') or 'dịch vụ/sản phẩm'
                    when = (h.get('created_at') or '')[:10]
                    lines.append(f"- {name} x{h.get('quantity') or 1}, ngày {when}")
                customer_snippet += (
                    "\n\nLỊCH SỬ MUA HÀNG/DỊCH VỤ GẦN NHẤT CỦA KHÁCH NÀY (dùng để nhắc lại, gợi ý "
                    "làm lại hoặc tư vấn nâng cấp đúng gu, không bịa thêm lần mua nào ngoài danh sách):\n"
                    + "\n".join(lines)
                )

            photos = AIContextEngine._load_recent_service_photos(business_id, customer_phone)
            if photos:
                lines = [
                    f"- {p.get('note') or 'Mẫu đã thực hiện'} (ngày {(p.get('created_at') or '')[:10]}): {p.get('image_url')}"
                    for p in photos
                ]
                customer_snippet += (
                    "\n\nẢNH MẪU DỊCH VỤ CŨ CỦA KHÁCH NÀY (có thể nhắc lại hoặc gợi ý làm lại mẫu tương tự "
                    "khi phù hợp với câu hỏi của khách):\n"
                    + "\n".join(lines)
                )

        upsell_directive = (
            "\n\nNHIỆM VỤ BÁN HÀNG: Khi khách hỏi hoặc đặt món/dịch vụ, hãy chủ động phân tích nhu cầu và "
            "khéo léo gợi ý thêm 1-2 sản phẩm/dịch vụ liên quan (upsell/cross-sell) từ ĐÚNG danh mục ở trên, "
            "ưu tiên món có giá trị cao hơn hoặc đi kèm hợp lý, không ép buộc, giữ giọng văn thân thiện tự nhiên. "
            "Luôn kết thúc bằng một câu hỏi mời khách xác nhận đặt hàng."
        )

        # Động hóa danh xưng: nếu xác định được tên cửa hàng thật (multi-tenant), AI phải tự
        # xưng danh là nhân viên CSKH của ĐÚNG cửa hàng đó, chỉ tư vấn theo danh mục thật ở trên.
        if business_name:
            identity_line = (
                f"\n\nBẠN LÀ AI CSKH CỦA: {business_name}. Luôn xưng danh là nhân viên tư vấn của {business_name} "
                f"khi phù hợp. Chỉ được tư vấn dựa trên đúng danh mục/bảng giá thật ở trên"
                + (", tuyệt đối không tự bịa thêm sản phẩm hoặc mức giá không có trong danh sách." if has_catalog else ".")
            )
        else:
            identity_line = ""

        full_prompt = f"{base_prompt} {custom_prompt}{identity_line}{details}{menu_snippet}{customer_snippet}{upsell_directive}"
        return {"prompt": full_prompt, "business_name": business_name}
