# Day 14 Lab - Mission Answers

> Môi trường: Windows 11 + WSL2 (Ubuntu), Python 3.14.4, Docker Desktop (tích hợp WSL2).

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong `01-localhost-vs-production/develop/app.py`:

1. **API key hardcode** (dòng 17): `OPENAI_API_KEY = "sk-hardcoded-..."`. Push lên GitHub là lộ key, và xoá đi vẫn còn trong lịch sử git.
2. **Database URL kèm mật khẩu hardcode** (dòng 18): `postgresql://admin:password123@localhost:5432/mydb`. Cùng lỗi như trên, lại cố định vào `localhost` nên không đổi được giữa các môi trường.
3. **Không có config management** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` viết cứng trong code. Muốn đổi phải sửa code và build lại.
4. **`print()` thay vì logging** (dòng 33, 36, 38): không có level, không có timestamp, không phải JSON nên log aggregator khó parse.
5. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Key nằm luôn trong log. Tôi đã thấy dòng này in ra thật khi chạy.
6. **Không có health check** (ghi chú dòng 42–43): `GET /health` trả 404 (đã đo). Nền tảng không biết agent đã crash để restart.
7. **Port cố định** (dòng 52): `port=8000`. Railway/Render truyền cổng qua biến `PORT`, nên app sẽ không nhận được traffic.
8. **Bind `host="localhost"`** (dòng 51): trong container chỉ nghe loopback, nên từ ngoài không kết nối được. Cần `0.0.0.0`.
9. **`reload=True`** (dòng 53): chế độ reload dành cho dev, tốn tài nguyên và không an toàn ở production.
10. **Không xử lý shutdown** (không có lifespan/SIGTERM): khi platform tắt container, request đang chạy có thể bị cắt giữa chừng.

### Exercise 1.2: Chạy bản develop

Chạy `python app.py` trong WSL, rồi gọi bằng curl:

```text
# Gửi JSON (theo CODE_LAB) -> bị từ chối
HTTP/1.1 422 Unprocessable Content
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

# Gửi question qua query (đúng với bản develop, xem README mục K5 số 3)
curl -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

# Health check
GET /health -> 404
```

Log của server khi nhận request có dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`, tức là secret bị in thẳng ra log.

**Nhận xét:** app chạy được nhưng chưa production-ready. Endpoint chỉ nhận `question` qua query chứ không nhận JSON, không có health check, lộ secret trong log, và không có cách cấu hình từ ngoài.

### Exercise 1.3: So sánh develop và production

Chạy `python app.py` trong `01-localhost-vs-production/production/`:

```text
GET  /health -> {"status":"ok","uptime_seconds":5.7,"version":"1.0.0","environment":"development",...}
GET  /ready  -> {"ready":true}
POST /ask {"question":"Hello"} -> 200 {"question":"Hello","answer":"...","model":"gpt-4o-mini"}
POST /ask {}                   -> 422
SIGTERM -> "Shutting down / Waiting for application shutdown / Application shutdown complete"
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`DEBUG = True`, key, URL) | Đọc từ env qua `config.py` (`os.getenv`), có `validate()` fail fast | Đổi cấu hình giữa dev/staging/prod mà không sửa code. Secret không nằm trong repo |
| Secrets | `sk-hardcoded-...` trong code và in ra log | `AGENT_API_KEY`, `OPENAI_API_KEY` lấy từ env, không log | Lộ secret là sự cố bảo mật, và xoá commit vẫn còn trong lịch sử git |
| Host/Port | `localhost`, `8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Container phải nghe `0.0.0.0`, còn Railway/Render cấp cổng qua `PORT` |
| Health check | Không có (`/health` trả 404) | `GET /health` (liveness) và `GET /ready` (readiness) | Nền tảng dựa vào đó để restart container chết và chỉ route traffic khi app sẵn sàng |
| Logging | `print()` | `logging` với format JSON, không log secret | Log dạng JSON dễ lọc và tìm trong Datadog/Loki, và có level để phân loại |
| Shutdown | Đột ngột, không có xử lý | `lifespan` + handler SIGTERM, log "shutting down gracefully" | Khi deploy hoặc scale-down, request đang chạy được hoàn thành thay vì bị cắt |
| Input validation | `question: str` qua query, không kiểm tra | Đọc JSON, trả 422 khi thiếu `question` | Trả lỗi rõ ràng thay vì để app lỗi 500 |
| Debug/reload | `reload=True` luôn bật | `reload=settings.debug`, mặc định tắt | Reload ở production tốn tài nguyên và không an toàn |

**Anti-pattern của develop mà production đã sửa:** `develop/app.py:17` hardcode `OPENAI_API_KEY`, còn `production/config.py:27` dùng `os.getenv("OPENAI_API_KEY", "")`.

**Vì sao hardcode secret nguy hiểm:** code được push lên Git nên key lộ cho mọi người có quyền đọc repo, và bot quét GitHub tìm key trong vài phút. Xoá file là chưa đủ vì key vẫn nằm trong lịch sử commit, nên phải thu hồi key.

**Vì sao cần health check và graceful shutdown:** health check cho phép nền tảng tự phát hiện và restart instance hỏng, còn `/ready` giữ traffic khỏi instance chưa sẵn sàng. Graceful shutdown bảo đảm khi nhận SIGTERM thì app ngừng nhận request mới và xử lý xong request đang chạy.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (dòng 8). Đây là bản Python đầy đủ, nặng.
2. **Working directory:** `/app` (dòng 11, `WORKDIR /app`).
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer, và một layer bị xoá cache thì mọi layer sau nó cũng build lại. Dependencies ít đổi còn source code đổi liên tục. Copy `requirements.txt` và `pip install` trước thì khi chỉ sửa code, bước cài dependencies (chậm nhất) được lấy từ cache. Nếu `COPY . .` đứng trước thì mỗi lần sửa một dòng code đều phải cài lại toàn bộ.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định và có thể bị ghi đè khi chạy (`docker run image <lệnh khác>`). `ENTRYPOINT` là chương trình cố định của container, và những gì truyền sau tên image chỉ được thêm vào làm tham số (muốn thay phải dùng `--entrypoint`). Hai thứ hay dùng cùng nhau: `ENTRYPOINT` là chương trình, `CMD` là tham số mặc định. Dockerfile này chỉ dùng `CMD ["python", "app.py"]` (dạng exec).

### Exercise 2.2: Build và run bản develop

Build từ gốc repo (README mục K5 số 4): `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`

```text
docker run -p 8000:8000 my-agent:develop
curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.1,"container":true}
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này có đủ công cụ build nhưng không được deploy.
- **Stage 2 (`runtime`):** từ `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (các package đã cài) và source code, rồi chạy bằng `appuser` với `HEALTHCHECK`.
- **Vì sao nhỏ hơn:** image cuối không chứa `gcc`, `libpq-dev`, cache của apt và pip, vì chúng chỉ nằm ở stage builder và bị bỏ đi. Ngoài ra base là `-slim` (bản `python:3.11` đầy đủ chứa nhiều gói không cần dùng).

Build: `docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .`

**Kích thước đo bằng `docker images my-agent` (không chép từ README):**

| Image | DISK USAGE | CONTENT SIZE | Bytes (`docker image inspect`) |
|---|---:|---:|---:|
| `my-agent:develop` | 1.67 GB | 426 MB | 1 667 771 672 |
| `my-agent:advanced` | 240 MB | 57.4 MB | 239 815 394 |

- Develop: **1.67 GB (1668 MB)**
- Production: **240 MB**
- Chênh lệch: **giảm 85.6%** (theo DISK USAGE, tính từ số byte: (1667771672 − 239815394) / 1667771672). Theo CONTENT SIZE (426 MB → 57.4 MB) là giảm khoảng 86.5%.
- Image production dưới 500 MB.

Chạy container production và kiểm tra:

```text
docker run -p 8000:8000 -e ENVIRONMENT=production my-agent:advanced
POST /ask {"question":"What is Docker?"} -> HTTP/1.1 200 OK
GET  /health -> {"status":"ok","uptime_seconds":4.2,"version":"2.0.0",...}
docker exec ... whoami -> appuser   (không chạy bằng root)
docker inspect ... .State.Health.Status -> healthy
```

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

Theo README mục K5 số 5 và số 7, tạo `.env.local` rỗng (đã nằm trong `.gitignore`) và chạy với `-p`:
`touch .env.local && docker compose -p k5-day14-docker up -d --build`

**Các service được start:** `agent` (FastAPI, build từ Dockerfile production), `redis` (`redis:7-alpine`), `qdrant` (`qdrant/qdrant:v1.9.0`), `nginx` (`nginx:alpine`).

```text
NAME                       IMAGE                   SERVICE   STATUS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up (healthy)    8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up              0.0.0.0:80->80, 0.0.0.0:443->443
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up (healthy)    6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up (healthy)    6379/tcp
```

**Sơ đồ kiến trúc:**

```text
                  Client (curl, cổng 80)
                         │
                         ▼
              ┌────────────────────┐
              │  nginx :80 / :443  │  reverse proxy + load balancer,
              │                    │  rate limit 10 req/s mỗi IP (burst 20 → 429)
              └─────────┬──────────┘
                        │ upstream agent_backend → agent:8000
                        ▼
              ┌────────────────────┐
              │ agent (FastAPI)    │  chỉ nằm trong mạng "internal",
              │ uvicorn, 2 workers │  không publish port ra host
              └───────┬─────┬──────┘
          REDIS_URL   │     │  QDRANT_URL
   redis://redis:6379 │     │  http://qdrant:6333
                      ▼     ▼
             ┌─────────┐   ┌─────────┐
             │  redis  │   │ qdrant  │   (có volume redis_data, qdrant_data)
             └─────────┘   └─────────┘
```

Các service giao tiếp qua mạng bridge `internal` và gọi nhau theo tên service (DNS của Docker). `agent` có `depends_on` với điều kiện `service_healthy` cho `redis` và `qdrant`, nên chỉ start sau khi hai service đó healthy. Chỉ nginx publish port ra ngoài.

**Kết quả test qua Nginx:**

```text
curl http://localhost/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":44.3,"version":"2.0.0","timestamp":"2026-11-25T08:54:03.479268"}

curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

**Ghi chú:** `main.py` của stack này chưa dùng Redis hay Qdrant (chỉ đọc biến `REDIS_URL`, `QDRANT_URL` trong compose), nên hai service này mới có vai trò chuẩn bị cho các bài sau. Xong bài, tôi đã tắt stack bằng `docker compose -p k5-day14-docker down`.

**Cần hiểu (CP2):** multi-stage giảm dung lượng bằng cách bỏ công cụ build khỏi image cuối. `COPY requirements.txt` đứng trước `COPY . .` để tận dụng cache layer của bước cài dependencies.

---

## AI log

> Theo RULES.md mục 1: ghi mỗi lần dùng AI cho code Part 6 hoặc câu trả lời.

| Lần | Phần | Hỏi gì | Nhận gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | Part 1 | Đọc `develop/app.py`, `production/app.py`, `production/config.py` và chạy cả hai bản trong WSL để lấy bằng chứng cho mục Part 1 | Danh sách anti-pattern, output curl và bảng so sánh | Các số dòng và output curl đến từ lệnh chạy thật trên máy tôi (dòng 17, 18, 21, 33, 34, 51–53 của develop; `/health` 404; 422 và 200 như trên). **TODO của tôi:** đọc lại đối chiếu với file gốc trước khi nộp |
| 2 | Part 2 | Đọc hai Dockerfile, `docker-compose.yml`, `nginx.conf`; build hai image, chạy container và stack Compose trong WSL để lấy số đo | Câu trả lời Exercise 2.1, giải thích multi-stage, sơ đồ stack | Kích thước (1.67 GB, 240 MB), `whoami`, trạng thái healthy, output curl qua Nginx đều lấy từ lệnh chạy thật. **TODO của tôi:** đọc lại các Dockerfile để tự giải thích được từng câu trả lời |
