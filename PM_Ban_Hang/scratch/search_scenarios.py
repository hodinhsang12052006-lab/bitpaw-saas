with open("app.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "scenarios" in line or "/api/bot" in line:
            print(f"Line {i}: {line.strip()}")
