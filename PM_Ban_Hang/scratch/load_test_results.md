# Load Test 100 Concurrent Users Report

- **Target**: http://127.0.0.1:5001
- **Concurrent Workers**: 100
- **Total Requests**: 520
- **Duration**: 5.64s
- **Success Rate**: 100.00%
- **Fail Rate**: 0.00%
- **p50 Latency**: 0.286s
- **p95 Latency**: 1.148s
- **Max Latency**: 1.629s
- **Average Latency**: 0.419s

## Endpoint Performance breakdown

### POST /api/submit_qr_order (Demo)
* Total Requests: 62
* Success Rate: 100.00%
* Average Latency: 0.1300s
* Max Latency: 0.3372s

### GET /kitchen_display
* Total Requests: 78
* Success Rate: 100.00%
* Average Latency: 0.1455s
* Max Latency: 0.3751s

### GET /
* Total Requests: 52
* Success Rate: 100.00%
* Average Latency: 0.1475s
* Max Latency: 0.3844s

### GET /landing
* Total Requests: 39
* Success Rate: 100.00%
* Average Latency: 0.1476s
* Max Latency: 0.3341s

### GET /table_order
* Total Requests: 58
* Success Rate: 100.00%
* Average Latency: 0.1499s
* Max Latency: 0.3463s

### GET /report
* Total Requests: 49
* Success Rate: 100.00%
* Average Latency: 0.9355s
* Max Latency: 1.6291s

### POST /api/cskh/request
* Total Requests: 48
* Success Rate: 100.00%
* Average Latency: 0.6449s
* Max Latency: 1.0574s

### GET /pos
* Total Requests: 46
* Success Rate: 100.00%
* Average Latency: 0.5985s
* Max Latency: 0.9174s

### GET /qr_menu/test
* Total Requests: 68
* Success Rate: 100.00%
* Average Latency: 0.7255s
* Max Latency: 1.1122s

### POST /api/ai/studio/generate
* Total Requests: 20
* Success Rate: 100.00%
* Average Latency: 1.1290s
* Max Latency: 1.4719s
