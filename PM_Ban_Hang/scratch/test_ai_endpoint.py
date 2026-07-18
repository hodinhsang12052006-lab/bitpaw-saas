import requests
import json

def test_api():
    url = "http://127.0.0.1:5001/api/ai/studio/generate"
    payload = {
        "systemPrompt": "Bạn là Mascot AI BitPaw tư vấn SaaS cho SME Việt Nam.",
        "userPrompt": "Tiệm nail của tôi có 12 thợ, hay tranh tua và tính hoa hồng rất mệt. BitPaw giúp gì?"
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"Sending POST request to {url}...")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"Status Code: {response.status_code}")
        print("Response Headers:")
        print(response.headers)
        
        try:
            res_json = response.json()
            print("Response JSON:")
            print(json.dumps(res_json, indent=4, ensure_ascii=False))
        except Exception as je:
            print(f"Failed to parse response as JSON. Error: {je}")
            print(f"Raw response: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_api()
