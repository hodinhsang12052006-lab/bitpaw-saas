import requests
import json

def test_ad_assistant():
    base_url = "http://127.0.0.1:5001/ad-assistant"
    
    # 1. Test GET /ad-assistant
    print("\n--- 1. Testing GET /ad-assistant ---")
    try:
        r1 = requests.get(base_url, timeout=10)
        print(f"Status Code: {r1.status_code}")
        if r1.status_code == 200:
            print("GET /ad-assistant: PASS")
        else:
            print(f"GET /ad-assistant: FAIL ({r1.status_code})")
    except Exception as e:
        print(f"Request error: {e}")
        
    # 2. Test POST /ad-assistant/api/suggest
    print("\n--- 2. Testing POST /ad-assistant/api/suggest ---")
    payload_suggest = {
        "product_name": "Combo Dưỡng Da Spa Cao Cấp",
        "product_desc": "Liệu trình trẻ hóa da bằng tinh chất thiên nhiên, bảo hành trọn đời.",
        "target_audience": {
            "age_min": 22,
            "age_max": 45,
            "interests": ["thẩm mỹ", "dưỡng da", "làm đẹp"]
        },
        "budget": 2000000,
        "platform": "facebook"
    }
    try:
        r2 = requests.post(f"{base_url}/api/suggest", json=payload_suggest, timeout=10)
        print(f"Status Code: {r2.status_code}")
        print("Response:", r2.text)
    except Exception as e:
        print(f"Request error: {e}")
        
    # 3. Test POST /ad-assistant/api/create-campaign (Use demo platform to avoid active Facebook Graph connection errors)
    print("\n--- 3. Testing POST /ad-assistant/api/create-campaign (Google platform demo) ---")
    payload_campaign = {
        "platform": "google",
        "name": "Chiến dịch Dưỡng Da Spa Google",
        "objective": "OUTCOME_TRAFFIC",
        "budget": 2000000
    }
    try:
        r3 = requests.post(f"{base_url}/api/create-campaign", json=payload_campaign, timeout=10)
        print(f"Status Code: {r3.status_code}")
        print("Response:", r3.text)
    except Exception as e:
        print(f"Request error: {e}")
        
    # 4. Test GET /ad-assistant/api/campaigns
    print("\n--- 4. Testing GET /ad-assistant/api/campaigns ---")
    try:
        r4 = requests.get(f"{base_url}/api/campaigns", timeout=10)
        print(f"Status Code: {r4.status_code}")
        print("Response:", r4.text)
    except Exception as e:
        print(f"Request error: {e}")

if __name__ == "__main__":
    test_ad_assistant()
