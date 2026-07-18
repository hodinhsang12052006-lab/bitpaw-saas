import urllib.request
import sys

base_url = "http://127.0.0.1:5001"
endpoints = {
    "Retail Pos (/sell)": "/sell",
    "Table Order (/table_order)": "/table_order",
    "QR Menu Test (/qr_menu/test)": "/qr_menu/test",
    "Kitchen Display (/kitchen_display)": "/kitchen_display"
}

print("[*] Testing response status for key modules...")
all_pass = True

for name, path in endpoints.items():
    url = f"{base_url}{path}"
    print(f"[*] Requesting {name}: {url}...")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.status
            print(f"    [+] Response Status: {status} OK")
            if status != 200:
                print(f"    [!] Warning: Expected 200 but got {status}")
                all_pass = False
    except Exception as e:
        print(f"    [!] Error requesting {url}: {str(e)}")
        all_pass = False

if all_pass:
    print("[+] ALL KEY MODULE ENDPOINTS ARE ONLINE AND RESPONDING WITH HTTP 200 OK!")
    sys.exit(0)
else:
    print("[!] SOME ENDPOINTS FAILED!")
    sys.exit(1)
