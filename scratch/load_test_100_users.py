import urllib.request
import urllib.parse
import json
import time
import threading
import statistics
import random

base_url = "http://127.0.0.1:5001"

# Danh sách kết quả lưu trữ của toàn bộ các request
results = []
results_lock = threading.Lock()

# Danh sách endpoints để test
endpoints = [
    {"name": "GET /", "path": "/", "method": "GET", "payload": None, "is_json": False},
    {"name": "GET /landing", "path": "/landing", "method": "GET", "payload": None, "is_json": False},
    {"name": "GET /pos", "path": "/pos", "method": "GET", "payload": None, "is_json": False},
    {"name": "GET /table_order", "path": "/table_order", "method": "GET", "payload": None, "is_json": False},
    {"name": "GET /qr_menu/test", "path": "/qr_menu/test", "method": "GET", "payload": None, "is_json": False},
    {"name": "GET /kitchen_display", "path": "/kitchen_display", "method": "GET", "payload": None, "is_json": False},
    {"name": "POST /api/submit_qr_order (Demo)", "path": "/api/submit_qr_order", "method": "POST", "payload": {"table_id": "9999", "items": [{"id": 1, "quantity": 2}], "total": 150000}, "is_json": True},
    {"name": "POST /api/cskh/request", "path": "/api/cskh/request", "method": "POST", "payload": {"name": "UAT Load Test", "phone": "0909999999", "email": "load_test@example.com", "message": "Concurrent test worker"}, "is_json": True},
    {"name": "GET /report", "path": "/report", "method": "GET", "payload": None, "is_json": False}
]

# AI Studio endpoint (test hạn chế để tránh rate-limit DeepSeek)
ai_endpoint = {
    "name": "POST /api/ai/studio/generate",
    "path": "/api/ai/studio/generate",
    "method": "POST",
    "payload": {
        "systemPrompt": "You are a fast responder",
        "userPrompt": "Ping short UAT check",
        "temperature": 0.1,
        "max_tokens": 10
    },
    "is_json": True
}

def make_request(ep):
    url = f"{base_url}{ep['path']}"
    data = None
    headers = {}
    
    if ep["payload"]:
        if ep["is_json"]:
            headers["Content-Type"] = "application/json"
            data = json.dumps(ep["payload"]).encode("utf-8")
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(ep["payload"]).encode("utf-8")
            
    req = urllib.request.Request(url, data=data, headers=headers, method=ep["method"])
    
    start_time = time.time()
    success = False
    status_code = 0
    error_msg = ""
    
    try:
        # Đặt timeout ngắn (5s) cho route thường, 10s cho AI
        timeout = 10 if "generate" in ep["path"] else 5
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            response.read() # consume body
            if status_code == 200:
                success = True
    except urllib.error.HTTPError as e:
        status_code = e.code
        error_msg = f"HTTPError {e.code}"
    except Exception as e:
        status_code = 500
        error_msg = str(e)
        
    duration = time.time() - start_time
    
    with results_lock:
        results.append({
            "name": ep["name"],
            "duration": duration,
            "success": success,
            "status_code": status_code,
            "error": error_msg
        })

def worker_thread(worker_id, num_requests_per_worker):
    # Mỗi worker sẽ gọi tuần tự các endpoints ngẫu nhiên
    for _ in range(num_requests_per_worker):
        ep = random.choice(endpoints)
        make_request(ep)
        
        # Chỉ 5% số requests là gọi thử AI studio để tránh nghẽn/tốn quota DeepSeek
        if random.random() < 0.05:
            make_request(ai_endpoint)
            
        time.sleep(random.uniform(0.1, 0.3)) # giả lập thời gian trễ giữa các hành động (thinking time)

def run_load_test(num_workers=100, requests_per_worker=5):
    print("======================================================================")
    print(f"STARTING PRODUCTION LOAD TEST WITH {num_workers} CONCURRENT WORKERS")
    print(f"Targeting: {base_url}")
    print("======================================================================")
    
    start_time = time.time()
    threads = []
    
    for i in range(num_workers):
        t = threading.Thread(target=worker_thread, args=(i, requests_per_worker))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    total_time = time.time() - start_time
    
    # Tính toán kết quả
    total_reqs = len(results)
    success_reqs = sum(1 for r in results if r["success"])
    fail_reqs = total_reqs - success_reqs
    success_rate = (success_reqs / total_reqs * 100) if total_reqs > 0 else 0
    fail_rate = 100 - success_rate
    
    latencies = [r["duration"] for r in results]
    
    p50 = statistics.median(latencies) if latencies else 0
    latencies.sort()
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[p95_idx] if latencies else 0
    max_latency = max(latencies) if latencies else 0
    avg_latency = sum(latencies)/len(latencies) if latencies else 0
    
    # Latency theo từng endpoint
    ep_stats = {}
    for r in results:
        ep_stats.setdefault(r["name"], []).append(r["duration"])
        
    print("\n======================================================================")
    print("LOAD TEST SUMMARY RESULTS")
    print("======================================================================")
    print(f"Total Concurrent Workers : {num_workers}")
    print(f"Total Requests Processed : {total_reqs}")
    print(f"Total Duration           : {total_time:.2f} seconds")
    print(f"Success Rate             : {success_rate:.2f}% ({success_reqs} requests)")
    print(f"Failure Rate             : {fail_rate:.2f}% ({fail_reqs} requests)")
    print(f"Average Latency          : {avg_latency:.3f} seconds")
    print(f"p50 (Median) Latency     : {p50:.3f} seconds")
    print(f"p95 Latency              : {p95:.3f} seconds")
    print(f"Max Latency              : {max_latency:.3f} seconds")
    print("======================================================================")
    
    print("\n--- LATENCY & SUCCESS RATE BY ENDPOINT ---")
    for name, durs in ep_stats.items():
        ep_success = sum(1 for r in results if r["name"] == name and r["success"])
        ep_total = len(durs)
        ep_success_rate = (ep_success / ep_total * 100)
        ep_avg = sum(durs) / ep_total
        print(f"[*] {name}:")
        print(f"    - Requests: {ep_total} | Success Rate: {ep_success_rate:.1f}%")
        print(f"    - Average Latency: {ep_avg:.3f}s | Max Latency: {max(durs):.3f}s")
        
    # Ghi nhận kết quả ra tệp tin MD
    report_content = f"""# Load Test 100 Concurrent Users Report

- **Target**: {base_url}
- **Concurrent Workers**: {num_workers}
- **Total Requests**: {total_reqs}
- **Duration**: {total_time:.2f}s
- **Success Rate**: {success_rate:.2f}%
- **Fail Rate**: {fail_rate:.2f}%
- **p50 Latency**: {p50:.3f}s
- **p95 Latency**: {p95:.3f}s
- **Max Latency**: {max_latency:.3f}s
- **Average Latency**: {avg_latency:.3f}s

## Endpoint Performance breakdown
"""
    for name, durs in ep_stats.items():
        ep_success = sum(1 for r in results if r["name"] == name and r["success"])
        ep_total = len(durs)
        ep_success_rate = (ep_success / ep_total * 100)
        ep_avg = sum(durs) / ep_total
        report_content += f"""
### {name}
* Total Requests: {ep_total}
* Success Rate: {ep_success_rate:.2f}%
* Average Latency: {ep_avg:.4f}s
* Max Latency: {max(durs):.4f}s
"""
    with open("scratch/load_test_results.md", "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print("\n[+] Report written to scratch/load_test_results.md")

if __name__ == "__main__":
    # Để test tải an toàn trên dev machine và Flask, dùng 100 workers và mỗi worker gửi 5 requests
    run_load_test(100, 5)
