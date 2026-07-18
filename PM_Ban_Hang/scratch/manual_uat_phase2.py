import urllib.request
import json
import sys

# Reconfigure stdout to use utf-8 encoding to avoid Windows console encoding issues
sys.stdout.reconfigure(encoding='utf-8')

url = "http://127.0.0.1:5001/api/ai/studio/generate"
headers = {
    "Content-Type": "application/json"
}

system_prompt = """Bạn là BitPaw AI Bot, nhân viên CSKH/tư vấn bán hàng của BitPaw OS.
Nói tiếng Việt tự nhiên như người thật, thân thiện, ngắn gọn.
Trả lời 2–5 câu, dưới 450 ký tự.
Không nói như robot, không văn mẫu dài, không spam bullet.
Luôn hỏi lại 1 câu ngắn để hiểu nhu cầu khách.
Nếu khách có nhu cầu rõ, mời để lại Zalo/số điện thoại để tư vấn flow.
Không lặp hotline ở mọi câu.
BitPaw OS hỗ trợ POS, QR Order, HRM, chấm công, tính lương, CRM, AI CSKH, marketing, tồn kho, báo cáo, thanh toán.
Nếu hỏi thanh toán QR: nói rõ demo đang xác nhận thủ công; tự động nhận diện tiền cần webhook/ngân hàng/cổng thanh toán.
Không hứa tính năng chưa chắc có.
Hotline/Zalo khi cần: 0794.678.904."""

test_cases = [
    "Tiệm nail của tôi có 12 thợ, hay tranh tua và tính hoa hồng rất mệt.",
    "Quán cafe của tôi có 15 bàn, muốn khách quét QR gọi món.",
    "Tôi muốn quản lý nhân viên và chấm công.",
    "Thanh toán QR có tự biết khách chuyển tiền chưa?",
    "Giá bao nhiêu?"
]

print("=== STARTING PHASE 2 AI CHATBOT UAT ===")
for idx, q in enumerate(test_cases, 1):
    payload = {
        "systemPrompt": system_prompt,
        "userPrompt": q,
        "temperature": 0.7,
        "max_tokens": 220,
        "source": "ai_bot_console"
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=25) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            reply = res_data["choices"][0]["message"]["content"].strip()
            print(f"\nCâu {idx}: {q}")
            print(f"-> Trả lời ({len(reply)} ký tự):\n{reply}")
    except Exception as e:
        print(f"\nCâu {idx}: {q}")
        print(f"-> Lỗi: {str(e)}")

print("\n=== UAT COMPLETED ===")
