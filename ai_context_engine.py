from supabase_client import supabase, SUPABASE_STATUS

class AIContextEngine:
    @staticmethod
    def _load_purchase_history(business_id, customer_phone, limit=5):
        """Trí nhớ dài hạn: các lần mua hàng/dùng dịch vụ gần nhất của ĐÚNG khách này
        (không phải tổng doanh thu chung), để AI biết khách từng mua gì, khi nào."""
        if SUPABASE_STATUS != "CONNECTED" or not business_id or not customer_phone:
            return []
        try:
            res = supabase.table('order_items') \
                .select('quantity, total_price, created_at, products(name, category)') \
                .eq('business_id', business_id).eq('customer_phone', customer_phone) \
                .order('created_at', desc=True).limit(limit).execute()
            return res.data or []
        except Exception:
            return []

    @staticmethod
    def _load_recent_service_photos(business_id, customer_phone, limit=3):
        """Ảnh mẫu dịch vụ cũ (vd: mẫu nail đã làm tháng trước) của ĐÚNG khách này,
        để AI có thể nhắc lại/gợi ý làm lại khi khách quay lại chat."""
        if SUPABASE_STATUS != "CONNECTED" or not business_id or not customer_phone:
            return []
        try:
            res = supabase.table('service_photos') \
                .select('image_url, note, created_at') \
                .eq('business_id', business_id).eq('customer_phone', customer_phone) \
                .order('created_at', desc=True).limit(limit).execute()
            return res.data or []
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
        if SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                biz = supabase.table('businesses').select('name, industry_code').eq('id', business_id).limit(1).execute()
                if biz.data:
                    business_name = biz.data[0].get('name') or None
                    industry_code = industry_code or biz.data[0].get('industry_code')
            except:
                pass

        if not industry_code:
            return {"prompt": base_prompt, "business_name": business_name}

        custom_prompt = industry_prompts.get(industry_code.lower(), "Bạn là chuyên gia tư vấn tăng trưởng.")

        # Load business metrics if connected — dữ liệu nhạy cảm, chỉ nhúng khi caller đã xác thực.
        revenue_sum = 0
        if include_private_data and SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                res = supabase.table('orders').select('total_amount').eq('business_id', business_id).execute()
                if res.data:
                    revenue_sum = sum([o.get('total_amount') or 0 for o in res.data])
            except:
                pass

        details = f"\n- Ngành nghề: {industry_code.upper()}\n- Quy mô: SaaS Enterprise"
        if include_private_data:
            details += f"\n- Báo cáo doanh thu hiện tại: {revenue_sum} VNĐ."

        # Nhúng menu/sản phẩm thật của tenant để AI gợi ý upsell/cross-sell đúng mặt hàng đang bán,
        # không bịa ra sản phẩm không tồn tại.
        menu_snippet = ""
        has_catalog = False
        if SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                prods = supabase.table('products').select('name, price, category') \
                    .eq('business_id', business_id).eq('is_active', 1).limit(40).execute()
                if prods.data:
                    has_catalog = True
                    lines = [
                        f"- {p.get('name')} ({p.get('category') or 'khác'}): {int(p.get('price') or 0):,}đ".replace(',', '.')
                        for p in prods.data
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
        if include_private_data and SUPABASE_STATUS == "CONNECTED" and business_id and customer_phone:
            try:
                cust = supabase.table('customers').select('name, tier, loyalty_points, total_spent') \
                    .eq('business_id', business_id).eq('phone', customer_phone).limit(1).execute()
                if cust.data:
                    c = cust.data[0]
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
