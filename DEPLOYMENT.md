# Deployment Information

## Public URL

https://day14-agent-ufm6.onrender.com

## Platform

Render (Blueprint từ `06-lab-complete/render.yaml`): một Web Service dạng Docker (`day14-agent`) và một Key Value (Redis) `day14-redis`, vùng Singapore, gói free.

Key Value của Render chạy Valkey 8 (tương thích giao thức Redis), nên `redis-py` trong agent kết nối bình thường và `/ready` trả 200.

Đây là chính agent của Part 6 (`06-lab-complete/`), không phải app mẫu trong `03-cloud-deployment/`.

> Gói free của Render ngủ khi không có traffic, nên request đầu tiên có thể mất 30–60 giây.

## Test Commands

Đặt `BASE` và `AGENT_API_KEY` (key đã đặt trên Render, không ghi trong repo):

```bash
export BASE=https://day14-agent-ufm6.onrender.com
read -rs AGENT_API_KEY; export AGENT_API_KEY
```

### Health Check

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS "$BASE/health"
# {"status":"ok","environment":"production"}
```

### Readiness (có kiểm tra kết nối Redis)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
```

### API Test: không có key (bị chặn)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'              # 401
```

### API Test: có key

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'                                                   # 200
```

### Kết quả đã chạy

| Lệnh | Mong đợi | Thực tế |
|---|---|---|
| `GET /health` | 200 | 200 |
| `GET /ready` | 200 | 200 |
| `POST /ask` không có key | 401 | 401 |
| `POST /ask` có `X-API-Key` đúng | 200 | 200 |

`python check_production_ready.py --public-url https://day14-agent-ufm6.onrender.com` cũng xác nhận `GET /health → 200` trên URL public.

## Environment Variables Set

Khai báo trong `render.yaml`, giá trị đặt trên nền tảng, không ghi trong code:

| Biến | Cách đặt | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | Render sinh (`generateValue: true`) | Secret, chỉ nằm trên Render |
| `REDIS_URL` | `fromService` → connection string của `day14-redis` | Tự nối từ Key Value, không gõ tay |
| `ENVIRONMENT` | `production` | |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` | `1.0` | |
| `MONTHLY_BUDGET_USD` | `10.0` | |
| `PORT` | Render tự cấp | Dockerfile lắng nghe theo `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
