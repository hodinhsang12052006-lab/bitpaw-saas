from flask import session
from supabase_client import supabase, SUPABASE_STATUS

class AIContextEngine:
    @staticmethod
    def build_context_prompt(business_id, industry_code):
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
        return f"{base_prompt} {custom_prompt} {details}"
