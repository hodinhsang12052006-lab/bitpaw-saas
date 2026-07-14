from supabase_client import supabase, SUPABASE_STATUS

class AIContextEngine:
    @staticmethod
    def build_context_prompt(business_id, industry_code, customer_phone=None):
        """Constructs an intelligent system prompt customized to the tenant's exact business DNA."""
        base_prompt = "Bạn là trợ lý chỉ chỉ huy BitPaw AI Copilot cho doanh nghiệp."

        if not industry_code:
            return base_prompt

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

        custom_prompt = industry_prompts.get(industry_code.lower(), "Bạn là chuyên gia tư vấn tăng trưởng.")

        # Load business metrics if connected
        revenue_sum = 0
        if SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                res = supabase.table('orders').select('total_amount').eq('business_id', business_id).execute()
                if res.data:
                    revenue_sum = sum([o.get('total_amount') or 0 for o in res.data])
            except:
                pass

        details = f"\n- Ngành nghề: {industry_code.upper()}\n- Quy mô: SaaS Enterprise\n- Báo cáo doanh thu hiện tại: {revenue_sum} VNĐ."

        # Nhúng menu/sản phẩm thật của tenant để AI gợi ý upsell/cross-sell đúng mặt hàng đang bán,
        # không bịa ra sản phẩm không tồn tại.
        menu_snippet = ""
        if SUPABASE_STATUS == "CONNECTED" and business_id:
            try:
                prods = supabase.table('products').select('name, price, category') \
                    .eq('business_id', business_id).eq('is_active', 1).limit(40).execute()
                if prods.data:
                    lines = [
                        f"- {p.get('name')} ({p.get('category') or 'khác'}): {int(p.get('price') or 0):,}đ".replace(',', '.')
                        for p in prods.data
                    ]
                    menu_snippet = (
                        "\n\nTHỰC ĐƠN/DANH MỤC SẢN PHẨM ĐANG BÁN (chỉ được gợi ý đúng các món dưới đây, "
                        "tuyệt đối không bịa thêm sản phẩm không có trong danh sách):\n" + "\n".join(lines)
                    )
            except:
                pass

        # Nhúng thông tin khách hàng (hạng thành viên, tổng chi tiêu = proxy cho lịch sử mua hàng)
        # nếu tra được theo SĐT, để AI cá nhân hoá lời tư vấn và ưu tiên gợi ý xứng tầm khách VIP.
        customer_snippet = ""
        if SUPABASE_STATUS == "CONNECTED" and business_id and customer_phone:
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

        upsell_directive = (
            "\n\nNHIỆM VỤ BÁN HÀNG: Khi khách hỏi hoặc đặt món/dịch vụ, hãy chủ động phân tích nhu cầu và "
            "khéo léo gợi ý thêm 1-2 sản phẩm/dịch vụ liên quan (upsell/cross-sell) từ ĐÚNG danh mục ở trên, "
            "ưu tiên món có giá trị cao hơn hoặc đi kèm hợp lý, không ép buộc, giữ giọng văn thân thiện tự nhiên. "
            "Luôn kết thúc bằng một câu hỏi mời khách xác nhận đặt hàng."
        )

        return f"{base_prompt} {custom_prompt} {details}{menu_snippet}{customer_snippet}{upsell_directive}"
