"""
Function Calling cho AI Bot (DeepSeek). Trước đây bot chỉ SINH VĂN BẢN ("Dạ em đã đặt lịch
cho chị rồi ạ") mà không ghi gì vào Database thật — khách tưởng đã đặt lịch nhưng thực tế
không có gì được lưu ("ảo giác"). Module này định nghĩa các tool THẬT mà DeepSeek được phép
gọi, được thực thi thật trong Python, và trả kết quả THẬT về cho AI để nó trả lời khách đúng
với những gì thực sự đã xảy ra — không còn tự bịa.
"""
import json
from datetime import datetime

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
    """Ghi 1 lịch hẹn THẬT vào bảng `appointments` (SQLite mã hoá SQLCipher — desktop_app/secure_db.py).
    Luôn raise ToolExecutionError khi có lỗi, không bao giờ trả về "coi như thành công" khi
    thực tế ghi DB thất bại."""
    if not all([business_id, customer_id, service_id, appointment_time]):
        raise ToolExecutionError(
            "Thiếu tham số bắt buộc (business_id/customer_id/service_id/appointment_time) — không thể đặt lịch."
        )

    try:
        parsed_time = datetime.fromisoformat(appointment_time)
    except ValueError as e:
        raise ToolExecutionError(
            f"appointment_time '{appointment_time}' không đúng định dạng ISO 8601."
        ) from e

    # Import trễ (không phải ở đầu module): desktop_app/secure_db.py cần sqlcipher3 + keyring,
    # 2 gói chỉ bắt buộc phải cài ở bản Desktop App. Nếu import ở đầu ai_function_tools.py,
    # môi trường Web/SaaS (không cài 2 gói này) sẽ sập ngay từ `import app` — book_appointment()
    # chỉ thực sự cần secure_db khi tool này ĐƯỢC GỌI (tức đang chạy Desktop mode, nơi 2 gói đó
    # chắc chắn đã được cài theo requirements.txt).
    try:
        from desktop_app.secure_db import engine
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError as e:
        raise ToolExecutionError(
            f"Chức năng đặt lịch chỉ khả dụng trên Desktop App (thiếu sqlalchemy/sqlcipher3/keyring ở môi trường này): {e}"
        ) from e

    try:
        with engine.begin() as conn:
            # Chặn double-book: cùng 1 tenant, cùng 1 khung giờ, chưa bị huỷ.
            clash = conn.execute(
                text("""
                    SELECT id FROM appointments
                    WHERE business_id = :business_id
                      AND appointment_time = :appointment_time
                      AND status != 'cancelled'
                """),
                {"business_id": business_id, "appointment_time": parsed_time.isoformat()},
            ).fetchone()
            if clash:
                raise ToolExecutionError(
                    f"Khung giờ {appointment_time} đã có khách khác đặt trước, cần chọn giờ khác."
                )

            result = conn.execute(
                text("""
                    INSERT INTO appointments (business_id, customer_id, service_id, appointment_time, status)
                    VALUES (:business_id, :customer_id, :service_id, :appointment_time, 'confirmed')
                """),
                {
                    "business_id": business_id,
                    "customer_id": customer_id,
                    "service_id": service_id,
                    "appointment_time": parsed_time.isoformat(),
                },
            )
            appointment_id = result.lastrowid
    except ToolExecutionError:
        raise
    except SQLAlchemyError as e:
        raise ToolExecutionError(f"Lỗi ghi Database khi đặt lịch: {e}") from e

    return {
        "success": True,
        "appointment_id": appointment_id,
        "service_id": service_id,
        "appointment_time": parsed_time.isoformat(),
        "status": "confirmed",
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
