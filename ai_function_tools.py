"""
Function Calling cho AI Bot (DeepSeek). Trước đây bot chỉ SINH VĂN BẢN ("Dạ em đã đặt lịch
cho chị rồi ạ") mà không ghi gì vào Database thật — khách tưởng đã đặt lịch nhưng thực tế
không có gì được lưu ("ảo giác"). Module này định nghĩa các tool THẬT mà DeepSeek được phép
gọi, được thực thi thật trong Python, và trả kết quả THẬT về cho AI để nó trả lời khách đúng
với những gì thực sự đã xảy ra — không còn tự bịa.

LỊCH SỬ: book_appointment() từng ghi vào bảng SQLite mã hoá SQLCipher (desktop_app/secure_db.py)
riêng cho Desktop App. Đã đổi sang ghi thẳng vào MongoDB `db.appointments` (cùng collection
blueprints/spa_bp.py dùng cho luồng đặt lịch công khai) vì 2 lý do: (1) app.py LUÔN dùng
mongo_client.py thật cho `db`, kể cả khi chạy Desktop App — local_db.py/MontyDB chưa từng được
nối vào app.py, nên bản SQLite kia là 1 kho dữ liệu cô lập, không có màn hình nào đọc lại được;
(2) route xem lịch (`/calendar`, app.py) chỉ có thể đọc 1 nguồn duy nhất cho cả Web lẫn Desktop
— Mongo là nguồn duy nhất sẵn có ở cả hai. Đánh đổi: mất tính chất "mã hoá tại chỗ" riêng cho
lịch hẹn trên máy Desktop — dữ liệu giờ nằm chung MongoDB Atlas như mọi collection khác.
"""
import json
from datetime import datetime

from mongo_client import db
from booking_engine import book_appointment as _book_appointment_shared, SlotAlreadyBookedError

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Đặt lịch hẹn THẬT cho khách hàng vào hệ thống. CHỈ gọi hàm này khi khách đã "
                "xác nhận RÕ RÀNG muốn đặt lịch và đã cung cấp đủ dịch vụ + thời gian mong "
                "muốn. KHÔNG được tự bịa service_id/thời gian nếu khách chưa nói rõ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "ID dịch vụ khách muốn đặt (lấy đúng từ danh sách dịch vụ đã cung cấp trong system prompt, không tự bịa).",
                    },
                    "appointment_time": {
                        "type": "string",
                        "description": "Thời gian hẹn, định dạng ISO 8601 (vd: 2026-08-01T14:00:00).",
                    },
                },
                "required": ["service_id", "appointment_time"],
            },
        },
    },
]


class ToolExecutionError(Exception):
    """Luôn được bắt ở execute_tool_call() và biến thành 1 tool-result báo lỗi rõ ràng gửi
    lại cho DeepSeek — KHÔNG BAO GIỜ được nuốt lỗi bằng pass/print, vì như vậy AI sẽ không
    biết việc ghi DB thất bại và có thể tiếp tục bịa với khách là đã đặt lịch thành công."""


def book_appointment(business_id, customer_id, service_id, appointment_time):
    """Ghi 1 lịch hẹn THẬT vào MongoDB `db.appointments` (cùng collection với
    blueprints/spa_bp.py::create_appointment — cùng schema để route /calendar đọc chung được
    cả 2 nguồn). Luôn raise ToolExecutionError khi có lỗi, không bao giờ trả về "coi như thành
    công" khi thực tế ghi DB thất bại."""
    if not all([business_id, customer_id, service_id, appointment_time]):
        raise ToolExecutionError(
            "Thiếu tham số bắt buộc (business_id/customer_id/service_id/appointment_time) — không thể đặt lịch."
        )
    if db is None:
        raise ToolExecutionError("Không có kết nối Database — không thể đặt lịch lúc này.")

    try:
        parsed_time = datetime.fromisoformat(appointment_time)
    except ValueError as e:
        raise ToolExecutionError(
            f"appointment_time '{appointment_time}' không đúng định dạng ISO 8601."
        ) from e
    book_time_str = parsed_time.isoformat()

    try:
        service_doc = db.products.find_one({'id': service_id, 'business_id': business_id}, {'_id': 0})
    except Exception as e:
        raise ToolExecutionError(f"Lỗi tra cứu dịch vụ trong Database: {e}") from e
    if not service_doc:
        raise ToolExecutionError(f"Không tìm thấy dịch vụ '{service_id}' của tiệm này — kiểm tra lại service_id.")

    # customer_id theo quy ước "business_id:phone" dùng chung toàn hệ thống (ai_bot.html,
    # _persist_chat_turn trong app.py) — tách ra để lưu customer_phone riêng, đúng schema cột
    # của spa_bp.py thay vì nhét customer_id thô vào.
    customer_phone = customer_id.split(':', 1)[1] if ':' in str(customer_id) else str(customer_id)
    try:
        customer_doc = db.bot_customers.find_one({'id': customer_id}, {'full_name': 1, '_id': 0})
    except Exception:
        customer_doc = None
    customer_name = (customer_doc or {}).get('full_name') or f"Khách AI Bot ({customer_phone})"

    # Dùng chung booking_engine.book_appointment() với UI đặt lịch công khai
    # (blueprints/spa_bp.py::create_appointment) — đảm bảo AI Bot và UI áp dụng ĐÚNG 1 rule
    # chống trùng lịch (theo staff_id + book_time), không lệch logic giữa 2 nguồn ghi.
    # staff_id=None ở đây vì AI Bot hiện chưa hỏi khách muốn chỉ định thợ nào — book_appointment()
    # chỉ check trùng khi có staff_id cụ thể, nên staff_id=None không kích hoạt check trùng lịch.
    try:
        appointment = _book_appointment_shared(
            business_id=business_id,
            customer_info={'name': customer_name, 'phone': customer_phone},
            staff_id=None,
            book_time=book_time_str,
            service_id=service_id,
            source='ai_bot',
        )
    except SlotAlreadyBookedError as e:
        raise ToolExecutionError(str(e)) from e
    except Exception as e:
        raise ToolExecutionError(f"Lỗi ghi Database khi đặt lịch: {e}") from e

    return {
        "success": True,
        "appointment_id": appointment['id'],
        "service_name": service_doc.get('name'),
        "appointment_time": book_time_str,
        "status": "pending",
    }


TOOL_DISPATCH = {
    "book_appointment": book_appointment,
}


def execute_tool_call(tool_call, business_id, customer_id):
    """Nhận 1 tool_call thô từ response của DeepSeek, thực thi hàm Python thật tương ứng, trả
    về (tool_call_id, content_str_json) để append vào messages với role="tool". Bắt TOÀN BỘ
    exception ở đây — 1 tool lỗi không được phép làm sập cả luồng chat; khách vẫn phải nhận
    được phản hồi (dù là báo lỗi trung thực), thay vì bot lặng lẽ bịa là đã xong."""
    function_name = tool_call.get("function", {}).get("name")
    raw_args = tool_call.get("function", {}).get("arguments") or "{}"
    tool_call_id = tool_call.get("id")

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        return tool_call_id, json.dumps(
            {"success": False, "error": f"AI trả về tham số không phải JSON hợp lệ: {e}"},
            ensure_ascii=False,
        )

    handler = TOOL_DISPATCH.get(function_name)
    if handler is None:
        return tool_call_id, json.dumps(
            {"success": False, "error": f"Không tìm thấy tool '{function_name}'."},
            ensure_ascii=False,
        )

    try:
        result = handler(business_id=business_id, customer_id=customer_id, **args)
        return tool_call_id, json.dumps(result, ensure_ascii=False)
    except ToolExecutionError as e:
        return tool_call_id, json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except TypeError as e:
        return tool_call_id, json.dumps(
            {"success": False, "error": f"Tool '{function_name}' được gọi với tham số không hợp lệ: {e}"},
            ensure_ascii=False,
        )
