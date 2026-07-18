with open("app.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "/nhanvien" in line or "/staff" in line or "/api/chamcong" in line or "/api/payroll" in line or "/bangluong" in line or "/cauhinh_luong" in line or "/map_dashboard" in line:
            print(f"Line {i}: {line.strip()}")
