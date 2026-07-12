import time
import requests
import cv2
import numpy as np
from mss import mss

# ================= CẤU HÌNH BOT =================
TELEGRAM_BOT_TOKEN = 'ĐIỀN_TOKEN_CỦA_ÔNG_VÀO_ĐÂY'
CHAT_ID = '-1004297640202'

# TỌA ĐỘ BẢNG GIỌT NƯỚC HIỆN TẠI (CHỈ 1 BẢNG 4x5)
# ÔNG PHẢI ĐO LẠI TRÊN MÀN HÌNH CỦA ÔNG CHO CHUẨN KHÍT CÁI BẢNG ĐÓ
WATER_DROP_REGION = {'top': 700, 'left': 400, 'width': 300, 'height': 200}

# ================= HÀM GỬI TELEGRAM =================
def send_telegram_signal(signal_type, method_name, vol, color_icon):
    message = f"{color_icon} **TÍN HIỆU LỆNH MỚI** {color_icon}\n\n"
    message += f"📊 Phương pháp: {method_name}\n"
    message += f"⚡️ Lệnh đánh: **{signal_type}**\n"
    message += f"💰 Đi lệnh: {vol}%\n"
    message += f"⏳ Vào lệnh ngay 30s này!"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        print(f"[+] Đã bắn tín hiệu: {signal_type} ({method_name})")
    except Exception as e:
        print(f"[-] Lỗi Telegram: {e}")

# ================= XỬ LÝ ẢNH & ĐỌC LƯỚI 4x5 =================
def extract_board_data(img):
    """Băm khung hình ra thành 5 cột, 4 hàng. Soi màu tâm từng ô."""
    h, w = img.shape[:2]
    cell_h, cell_w = h // 4, w // 5
    
    grid = [['' for _ in range(4)] for _ in range(5)] # 5 cột, 4 hàng
    history = []
    
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    for col in range(5):
        for row in range(4):
            # Lấy tọa độ tâm của từng ô giọt nước
            cx = int((col + 0.5) * cell_w)
            cy = int((row + 0.5) * cell_h)
            
            # Lấy màu tại tâm ô đó
            pixel_hsv = hsv[cy, cx]
            h_val, s_val, v_val = pixel_hsv
            
            # Phân loại Xanh (B) hay Đỏ (S). Chỉ nhận khi độ bão hòa (S) đủ cao, bỏ qua màu xám/đen
            if s_val > 50 and v_val > 50: 
                if 40 <= h_val <= 85: # Dải màu xanh lá
                    grid[col][row] = 'B'
                    history.append('B')
                elif h_val <= 10 or h_val >= 160: # Dải màu đỏ
                    grid[col][row] = 'S'
                    history.append('S')
    
    return grid, history

# ================= LOGIC 8 CÔNG THỨC =================
def apply_8_formulas(history):
    if len(history) < 3:
        return
    last_3 = "".join(history[-3:])
    
    formulas = {
        "BBS": "BUY", "SSB": "SELL",
        "BSB": "BUY", "SBS": "SELL",
        "BBB": "BUY", "SSS": "SELL",
        "SBB": "SELL", "BSS": "BUY"
    }
    
    if last_3 in formulas:
        signal = formulas[last_3]
        icon = "🟢" if signal == "BUY" else "🔴"
        send_telegram_signal(signal, f"Chuỗi ({last_3})", 1, icon)

# ================= LOGIC NHỊ KIẾM =================
def apply_nhi_kiem(grid):
    # Tìm cột mới nhất có chứa giọt nước hàng số 2
    for col in range(4, 0, -1): # Lùi từ cột cuối (cột 4) về cột 1
        if grid[col-1][1] != '' and grid[col][0] == '': 
            # Có tín hiệu ở Cột trước (Hàng 2), và Cột hiện tại (Hàng 1) đang chờ đánh
            signal_color = grid[col-1][1]
            target = "BUY" if signal_color == 'B' else "SELL"
            icon = "🟢" if target == "BUY" else "🔴"
            send_telegram_signal(target, "Nhị Kiếm (Hàng 1)", 1, icon)
            break
        elif grid[col-1][1] != '' and grid[col][0] != '' and grid[col][2] == '':
            # Nếu đã đánh Hàng 1 mà loss (màu khác nhau), gấp lệnh đánh Hàng 3
            if grid[col][0] != grid[col-1][1]:
                signal_color = grid[col-1][1]
                target = "BUY" if signal_color == 'B' else "SELL"
                icon = "🟢" if target == "BUY" else "🔴"
                send_telegram_signal(target, "Nhị Kiếm (Gấp Hàng 3)", 2, icon)
            break

# ================= VÒNG LẶP THEO DÕI SÀN =================
def main():
    print("🚀 Bot Đang Chạy... Đang bám nhịp 60s của sàn!")
    last_history_length = 0
    
    with mss() as sct:
        while True:
            try:
                # 1. Chụp bảng giọt nước
                img = np.array(sct.grab(WATER_DROP_REGION))
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR) # Bỏ kênh Alpha
                
                # 2. Đọc dữ liệu ra lưới 4x5 và mảng lịch sử
                grid, history = extract_board_data(img)
                
                # 3. Check nhịp sàn: Nếu mảng lịch sử tăng thêm 1 (tức là có 1 giọt nước mới vừa chốt)
                # Nghĩa là vừa hết 30s kết quả -> Bắt đầu 30s đặt lệnh -> BẮN LỆNH!
                current_length = len(history)
                
                if current_length > last_history_length:
                    print(f"[*] Có kết quả mới! Tổng số nến hiện tại: {current_length}")
                    
                    # Bắn tín hiệu 8 công thức
                    apply_8_formulas(history)
                    
                    # Bắn tín hiệu Nhị Kiếm
                    apply_nhi_kiem(grid)
                    
                    # Cập nhật lại số lượng
                    last_history_length = current_length
                    
                # Quét liên tục 1 giây 1 lần để không trượt nhịp đổi nến nào
                time.sleep(1)
                
            except Exception as e:
                print(f"[-] Lỗi trong lúc soi chạc: {e}")
                time.sleep(5)

if __name__ == "__main__":
    main()