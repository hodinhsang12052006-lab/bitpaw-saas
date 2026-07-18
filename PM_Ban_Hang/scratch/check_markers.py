import urllib.request

def check_url(url, marker):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            html = response.read().decode('utf-8')
            if marker in html:
                print(f"SUCCESS: Found '{marker}' in {url}")
                return True
            else:
                print(f"FAILED: '{marker}' NOT found in {url}")
                return False
    except Exception as e:
        print(f"ERROR fetching {url}: {e}")
        return False

print("--- VERIFYING UAT MARKERS ON RUNNING APP ---")
check_url("http://127.0.0.1:5001/landing", "UAT-LANDING-AIBOT-3D-MARKER")
