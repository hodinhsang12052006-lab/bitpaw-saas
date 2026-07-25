#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vercel_deploy_pro.py — Tu dong hoa cap nhat bien moi truong len 1 project Vercel
va deploy production, dung Vercel CLI (subprocess), KHONG dung Playwright /
browser automation / bat ky thao tac click UI nao.

Vi sao dung CLI thay vi REST API o script nay: may dang chay da dang nhap san qua
`vercel login` (xac nhan bang `vercel whoami`) - dung luon CLI it rui ro hon vi
khong can tu quan ly token rieng.

--- BAI HOC RUT RA TU CAC LAN CHAY TRUOC (QUAN TRONG) ---
1) `vercel redeploy <url-cu>` REBUILD DUNG SNAPSHOT BIEN MOI TRUONG TAI THOI DIEM
   deployment GOC do duoc tao - KHONG doc gia tri bien moi truong MOI NHAT. Muon
   bien moi MOI thuc su duoc ap dung, BAT BUOC phai tao deployment HOAN TOAN MOI
   (`vercel deploy --prod`), khong phai redeploy 1 ban cu.

2) TAI KHOAN VERCEL CO THE CO NHIEU PROJECT TRUNG CODEBASE (vd do tao nham/test
   nhieu lan) - domain that (bitpawsoftware.com) co the thuoc VE 1 PROJECT KHAC
   voi project ma thu muc local dang duoc `.vercel/repo.json` link toi. Script
   nay BAT BUOC nhan tham so --project ro rang, KHONG doan/mac dinh theo link cu
   bo, de tranh sua nham project khong lien quan gi den domain that.

`vercel deploy --prod` dong goi va deploy TOAN BO thu muc local hien tai - neu
dang co thay doi code CHUA COMMIT, no se bi day len production theo luon, vuot
pham vi "chi doi bien moi truong". Script nay tu kiem tra `git status` truoc khi
deploy: neu phat hien file code app (app.py/templates/static css-js) dang thay
doi chua commit, DUNG LAI va bao cho nguoi dung tu quyet dinh (commit/stash) thay
vi tu y stash/commit thay - day la quyet dinh nguoi dung nen tu kiem soat.

AN TOAN:
  - Gia tri bien moi truong chi doc tu file .env local, KHONG BAO GIO in nguyen
    van ra terminal/log - moi cho hien thi deu qua ham mask().
  - Dung --sensitive cho moi bien (MONGO_URI, cac hash, FLASK_SECRET_KEY) - Vercel
    se KHONG cho doc lai gia tri nay qua `env pull`/dashboard sau khi tao (chi
    hien "[SENSITIVE]") - day la tinh nang bao mat co chu y cua Vercel, khong
    phai loi/gioi han cua script.
  - Dung `--force` de ghi de bien da ton tai trong 1 lenh (khong can rm truoc).

CHAY:
    python vercel_deploy_pro.py --project bitpaw-saas-web
    python vercel_deploy_pro.py --project bitpaw-software
"""

import argparse
import os
import re
import sys
import subprocess
import time

# Windows console mac dinh dung cp1252, khong encode duoc chu co dau tieng Viet ->
# ep lai stdout/stderr sang UTF-8 de tranh UnicodeEncodeError khi print().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ENV_FILE = ".env"
TARGET_VARS = [
    "MONGO_URI",
    "SUPERADMIN_FALLBACK_HASH_B64",
    "SUPERADMIN_FALLBACK_HASH",
    "FLASK_SECRET_KEY",
]
TARGET_ENV = "production"

# Cac duong dan neu dang co thay doi CHUA COMMIT thi coi la rui ro (anh huong runtime
# app khi deploy) - khac voi anh test/screenshot khong lien quan gi den Flask.
RISKY_PATH_PREFIXES = ("app.py", "templates/", "static/css/", "static/js/", "mongo_client.py", "i18n.py")


def mask(value, keep=6):
    if not value:
        return "(rỗng)"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]} ({len(value)} ký tự)"


def run(cmd, input_text=None, timeout=60):
    """Chay 1 lenh subprocess, tra ve (returncode, stdout, stderr).

    Tren Windows, npm cai global CLI (vd 'vercel') thanh file '.cmd' shim, khong
    phai '.exe' that - WinAPI CreateProcess (dung boi subprocess khi shell=False)
    khong tu resolve duoc '.cmd' qua PATH, gay FileNotFoundError. Fix chuan cho
    truong hop nay: bat shell=True TREN WINDOWS. Van truyen cmd duoi dang list (
    khong noi chuoi thu cong) de Python tu quote tung phan tu qua list2cmdline -
    gia tri (--value ...) luon lay tu file .env local dang tin cay, khong phai
    input tu nguoi dung/attacker, nen rui ro injection qua ky tu dac biet cua
    cmd.exe la khong dang ke trong ngu canh nay."""
    use_shell = sys.platform.startswith("win")
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=use_shell,
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_env_file(path):
    if not os.path.exists(path):
        print(f"[LỖI] Không tìm thấy file {path}.")
        sys.exit(1)
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def check_prereqs(project):
    print("[1/6] Kiểm tra điều kiện tiên quyết...")

    rc, out, err = run(["vercel", "--version"])
    if rc != 0:
        print("[LỖI] Chưa cài Vercel CLI. Chạy lệnh sau rồi chạy lại script này:")
        print("      npm install -g vercel")
        sys.exit(1)
    print(f"      Vercel CLI: {out.strip()}")

    rc, out, err = run(["vercel", "whoami"])
    if rc != 0:
        print("[LỖI] Vercel CLI chưa đăng nhập. Chạy lệnh sau, đăng nhập xong rồi chạy lại script này:")
        print("      vercel login")
        sys.exit(1)
    print(f"      Đã đăng nhập: {out.strip()}")

    # Xac nhan project ton tai va lay danh sach domain that su gan vao no - de nguoi
    # dung tu doi chieu dung project truoc khi script ghi bat cu thu gi.
    rc, out, err = run(["vercel", "project", "inspect", project], timeout=30)
    if rc != 0:
        print(f"[LỖI] Không tìm thấy project '{project}' trong tài khoản đang đăng nhập.")
        print(f"      {err.strip()[:300]}")
        sys.exit(1)
    print(f"      Project xác nhận tồn tại: {project}")


def check_git_clean_for_deploy():
    """`vercel deploy --prod` dong goi TOAN BO thu muc local - neu co file code app
    (app.py/templates/static css-js) dang sua do chua commit, DUNG lai thay vi tu
    y quyet dinh stash/commit thay nguoi dung. Anh test/screenshot khong tinh vi
    khong anh huong runtime Flask khi deploy."""
    print("\n[2/6] Kiểm tra git status trước khi deploy (tránh đẩy code chưa duyệt lên production)...")
    rc, out, err = run(["git", "status", "--porcelain"], timeout=15)
    if rc != 0:
        print(f"      [CẢNH BÁO] Không chạy được 'git status' ({err.strip()[:200]}) — bỏ qua kiểm tra này.")
        return True

    dirty_files = [line[3:].strip() for line in out.splitlines() if line.strip()]
    risky = [f for f in dirty_files if f.startswith(RISKY_PATH_PREFIXES)]

    if risky:
        print("      [DỪNG] Phát hiện file code app ĐANG SỬA, CHƯA COMMIT:")
        for f in risky:
            print(f"             - {f}")
        print("      Không tự ý deploy để tránh đẩy code chưa duyệt lên production.")
        print("      Hãy tự commit (hoặc `git stash`) các file trên rồi chạy lại script.")
        return False

    if dirty_files:
        print(f"      Có {len(dirty_files)} file thay đổi chưa commit nhưng không ảnh hưởng runtime app (vd ảnh test) — tiếp tục.")
    else:
        print("      Working directory sạch — an toàn để deploy.")
    return True


def sync_env_vars(project, env_data):
    print(f"\n[3/6] Đồng bộ biến môi trường lên Vercel project '{project}' (target: production)...")
    all_ok = True
    for key in TARGET_VARS:
        value = env_data.get(key)
        if not value:
            print(f"      [BỎ QUA] '{key}' không có trong {ENV_FILE}.")
            continue

        print(f"      -> {key} = {mask(value)}")
        cmd = [
            "vercel", "env", "add", key, TARGET_ENV,
            "--value", value,
            "--yes", "--force", "--sensitive",
            "--project", project,
        ]
        rc, out, err = run(cmd, timeout=30)
        if rc == 0:
            print(f"         [OK] Đã ghi '{key}' lên project '{project}'.")
        else:
            print(f"         [LỖI] Ghi '{key}' thất bại (mã {rc}): {err.strip()[:300]}")
            all_ok = False
    return all_ok


def fresh_deploy_prod(project):
    """Tao 1 deployment HOAN TOAN MOI cho dung PROJECT duoc chi dinh (khong phai
    project dang link mac dinh cua thu muc local, tranh sua nham) - day la buoc
    BAT BUOC de bien moi truong vua cap nhat thuc su duoc ap dung."""
    print(f"\n[4/6] Tạo deployment MỚI HOÀN TOÀN cho project '{project}' (để đọc đúng biến môi trường vừa cập nhật)...")
    rc, out, err = run(["vercel", "deploy", "--prod", "--yes", "--project", project], timeout=300)
    text = (out or "") + (err or "")
    urls = re.findall(r"https://[^\s]+\.vercel\.app", text)
    deployment_url = urls[-1] if urls else None

    if rc == 0 and deployment_url:
        print(f"      [OK] Deploy thành công: {deployment_url}")
        return deployment_url

    print(f"      [LỖI] Deploy thất bại (mã {rc}): {err.strip()[:500] or out.strip()[:500]}")
    return None


def verify_deployment_ready(deployment_url, attempts=6, wait_seconds=10):
    print("\n[5/6] Xác nhận deployment đã Ready (không chỉ tin lệnh deploy trả về 0)...")
    for i in range(attempts):
        rc, out, err = run(["vercel", "inspect", deployment_url], timeout=30)
        text = out + err
        if "● Ready" in text or "Ready" in text:
            print("      [OK] Deployment status: Ready.")
            return True
        if "Error" in text or "Failed" in text:
            print(f"      [LỖI] Deployment status: Error/Failed.\n{text[:500]}")
            return False
        print(f"      ... đang build, chờ thêm ({i + 1}/{attempts})...")
        time.sleep(wait_seconds)
    print("      [CẢNH BÁO] Hết thời gian chờ xác nhận — kiểm tra thủ công trên Vercel Dashboard.")
    return False


def verify_custom_domain(domain):
    """Kiem tra domain that (khong phai .vercel.app) da het loi chua - dung curl
    qua subprocess de khong phu thuoc thu vien ngoai (requests) cho buoc nay."""
    print(f"\n[6/6] Kiểm tra domain thật https://{domain}/login ...")
    # -L bat buoc phai co: bitpawsoftware.com hay redirect (308) sang www.bitpawsoftware.com,
    # thieu -L thi curl chi nhan noi dung rong cua response redirect, khong phai trang /login
    # that - gay bao "khong con loi" GIA (da gap phai o lan chay dau, phai kiem tra lai thu cong).
    rc, out, err = run(["curl", "-sk", "-L", "-o", "-", "-w", "\\nHTTP_CODE:%{http_code}", f"https://{domain}/login"], timeout=30)
    if rc != 0:
        print(f"      [CẢNH BÁO] Không curl được domain thật: {err.strip()[:300]}")
        return None
    code_match = re.search(r"HTTP_CODE:(\d+)", out)
    code = code_match.group(1) if code_match else "?"
    has_error_text = "thiếu cấu hình" in out.lower() or "hệ thống thiếu" in out.lower()
    print(f"      HTTP: {code}")
    print(f"      Còn thấy thông báo lỗi cấu hình Key bảo mật trong HTML: {'CÓ' if has_error_text else 'KHÔNG'}")
    return not has_error_text


def main():
    parser = argparse.ArgumentParser(description="Cập nhật env vars + deploy production cho 1 Vercel project cụ thể.")
    parser.add_argument("--project", required=True, help="Tên (hoặc ID) CHÍNH XÁC của Vercel project cần cập nhật — KHÔNG suy đoán mặc định, vì tài khoản có thể có nhiều project trùng codebase.")
    parser.add_argument("--verify-domain", default=None, help="Domain thật để curl kiểm chứng sau khi deploy xong (vd: bitpawsoftware.com). Tuỳ chọn.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"VERCEL_DEPLOY_PRO — project: {args.project}")
    print("=" * 70)

    check_prereqs(args.project)

    if not check_git_clean_for_deploy():
        sys.exit(1)

    env_data = parse_env_file(ENV_FILE)
    missing = [k for k in TARGET_VARS if not env_data.get(k)]
    if missing:
        print(f"\n[LỖI] Thiếu {missing} trong {ENV_FILE}. Dừng lại, không đổi gì trên Vercel.")
        sys.exit(1)

    env_ok = sync_env_vars(args.project, env_data)
    if not env_ok:
        print("\n[DỪNG] Có biến cập nhật thất bại — không tiếp tục deploy để tránh")
        print("        chạy production với cấu hình môi trường không đầy đủ/không nhất quán.")
        sys.exit(1)

    deployment_url = fresh_deploy_prod(args.project)
    if not deployment_url:
        print("\n[DỪNG] Deploy thất bại — biến môi trường ĐÃ được cập nhật, nhưng chưa có")
        print("        deployment mới nào áp dụng chúng. Kiểm tra log lỗi ở trên rồi chạy lại.")
        sys.exit(1)

    ready = verify_deployment_ready(deployment_url)

    domain_ok = None
    if args.verify_domain:
        domain_ok = verify_custom_domain(args.verify_domain)

    print("\n" + "=" * 60)
    if ready:
        print(f"HOÀN TẤT: {len(TARGET_VARS)} biến môi trường đã cập nhật cho '{args.project}' + deployment MỚI đã Ready.")
        print(f"URL: {deployment_url}")
        if domain_ok is True:
            print(f"Domain {args.verify_domain}: KHÔNG còn lỗi cấu hình Key bảo mật.")
        elif domain_ok is False:
            print(f"Domain {args.verify_domain}: VẪN còn thấy lỗi — có thể do domain này alias vào project/deployment khác, hoặc cache CDN chưa hết. Kiểm tra thủ công.")
    else:
        print("Deploy đã chạy nhưng CHƯA xác nhận được trạng thái Ready — kiểm tra")
        print(f"thủ công: vercel inspect {deployment_url}")
        sys.exit(1)


if __name__ == "__main__":
    main()
