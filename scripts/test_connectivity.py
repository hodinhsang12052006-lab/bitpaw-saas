import requests

try:
    s = requests.Session()
    # Check if app is responding
    res = s.get('http://127.0.0.1:5001/login')
    print("Login page status:", res.status_code)
except Exception as e:
    print("Connection error:", e)
