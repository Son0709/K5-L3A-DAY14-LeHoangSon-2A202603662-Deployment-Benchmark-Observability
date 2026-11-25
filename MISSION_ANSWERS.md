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

## Part 3: Cloud Deployment

> Theo CHECKPOINTS (CP6) và README mục K5 số 8, tôi deploy chính agent Part 6 (`06-lab-complete/`), không deploy app mẫu trong `03-cloud-deployment/`.

### Exercise 3.1 / 3.2: Deploy

- **Nền tảng chính:** Render (Exercise 3.2), deploy bằng Blueprint từ `06-lab-complete/render.yaml` (Web Service + Key Value Redis).
- **URL public:** https://day14-agent-ufm6.onrender.com
- **Ảnh:** [dashboard](screenshots/dashboard.png), [running](screenshots/running.png), [test](screenshots/test.png) (chi tiết trong `DEPLOYMENT.md`)

4 lệnh tự kiểm của CP6 trên URL public (chỉ in mã HTTP, không lộ key):

```text
GET  /health                      -> 200
GET  /ready                       -> 200   (Redis trên Render đã kết nối)
POST /ask (không có key)          -> 401
POST /ask (X-API-Key đúng)        -> 200
```

Lần đầu thử có key tôi nhận 401 vì giá trị key trong terminal không khớp key đang chạy trên Render. Nhập lại đúng giá trị hiện tại trên dashboard thì trả 200, nên lỗi nằm ở cách nhập key chứ không ở code.

### So sánh `railway.toml` với `render.yaml`

Hai file cùng lo phần "nền tảng build và chạy container thế nào", nhưng khác nhau về phạm vi:

| Điểm | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Chỉ mô tả **một service**: cách build (`builder = "DOCKERFILE"`) và cách deploy (`healthcheckPath = "/health"`, chính sách restart) | Mô tả **cả hệ thống** (Blueprint / Infrastructure as Code): web service **và** Redis (`type: keyvalue`) khai báo cùng một file |
| Biến môi trường | Không nằm trong file. Đặt bằng `railway variables set` hoặc dashboard | Khai báo ngay trong file: giá trị cố định (`ENVIRONMENT`), secret sinh tự động (`AGENT_API_KEY` dùng `generateValue: true`), và **nối thẳng sang service khác** (`REDIS_URL` lấy từ `fromService` → Redis `connectionString`) |
| Redis | Phải tự thêm service Redis trong dashboard, rồi gán `REDIS_URL` bằng tay | Được tạo cùng lúc và tự nối vào web service, nên không cần thao tác tay |
| Cách deploy | `railway up` đẩy thư mục **cục bộ** lên (CLI push) | Render đọc repo **GitHub** (`autoDeploy: true`), tức push là deploy |
| Đường dẫn Dockerfile | Chạy `railway up` ngay trong `06-lab-complete/` nên Dockerfile ở thư mục hiện tại | File nằm trong thư mục con, mà đường dẫn tính từ gốc repo. Gốc repo có một `Dockerfile` khác, nên phải ghi rõ `./06-lab-complete/Dockerfile` kẻo build nhầm |
| Plan, region | Đặt trong dashboard | Ghi trong file (`plan: free`, `region: singapore`) |

**Vì sao khác nhau:** Railway coi `railway.toml` là cấu hình bổ sung cho một service tạo qua CLI hoặc dashboard (trải nghiệm theo kiểu thao tác trực tiếp). Render thiết kế `render.yaml` để mô tả toàn bộ hạ tầng theo cách khai báo, lấy từ Git. Hệ quả thực tế: ở Render, bài này gần như deploy một lần được cả agent và Redis, còn ở Railway tôi phải tự tạo Redis và đặt `REDIS_URL`.

**Điểm chung:** cả hai đều dùng cùng `Dockerfile`, cùng `healthcheckPath = /health`, và cùng việc app lắng nghe theo biến `PORT` do nền tảng cấp (CMD dùng `${PORT:-8000}`). Dockerfile không phải sửa gì để chạy được trên hai nơi.

### Exercise 3.3: Cloud Run pipeline (chỉ đọc, không deploy)

`cloudbuild.yaml` định nghĩa pipeline CI/CD 4 bước chạy tuần tự (mỗi bước `waitFor` bước trước), kích hoạt khi push lên `main`: **(1) test**: cài dependencies và chạy `pytest tests/`, nếu lỗi thì dừng cả pipeline; **(2) build**: build Docker image, gắn tag theo `$COMMIT_SHA` và `latest`, dùng `--cache-from` để tái sử dụng layer; **(3) push**: đẩy mọi tag lên Container Registry; **(4) deploy**: `gcloud run deploy` image theo commit SHA lên Cloud Run vùng `asia-southeast1`, đặt `min-instances=1` (tránh cold start), `max-instances=10`, và lấy `OPENAI_API_KEY` từ Secret Manager thay vì ghi trong code. `service.yaml` là bản mô tả cùng service theo dạng khai báo (Knative): giới hạn tài nguyên (1 CPU, 512Mi), `containerConcurrency: 80`, secret `OPENAI_API_KEY` và `AGENT_API_KEY` từ Secret Manager, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`, đúng mô hình liveness và readiness đã học ở Part 5.

Hai điểm tôi thấy lệch khi đọc: pipeline chạy `pytest tests/` mà lab không có thư mục `tests/`, nên chạy thật sẽ đỏ ở bước 1; và bước deploy chỉ gắn secret `OPENAI_API_KEY`, còn `service.yaml` gắn thêm `AGENT_API_KEY`, nên hai file chưa đồng bộ.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

Chạy bằng `AGENT_API_KEY=secret-key-123 python app.py` (README mục K5 số 6).

- **API key được check ở đâu?** Hàm `verify_api_key` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader`, so với biến `API_KEY` lấy từ env `AGENT_API_KEY` (dòng 35). Endpoint `/ask` gắn nó bằng `Depends(verify_api_key)` (dòng 70). `/` và `/health` để public.
- **Sai key thì sao?** Thiếu key trả **401**, sai key trả **403** (xem output dưới). Lưu ý bản Part 6 yêu cầu cả hai trường hợp đều là 401.
- **Rotate key thế nào?** Đổi giá trị biến `AGENT_API_KEY` rồi restart service. Không cần sửa code hay build lại image. Vì key chỉ đọc từ env nên đổi trên dashboard của nền tảng là đủ.

```text
# Không có key
curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key
curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong" ...
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Đúng key
curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" ...
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

Theo README mục K5 số 6: lấy token ở `POST /auth/token` với `student` / `demo123` (không phải `/token` và `admin`/`secret` như CODE_LAB). Tôi cũng thử đường dẫn cũ: `POST /token` trả **404**.

**JWT flow (`auth.py`):** `POST /auth/token` kiểm tra username/password (`authenticate_user`), rồi `create_token` ký payload `{sub, role, iat, exp}` bằng HS256 với `JWT_SECRET` (hết hạn sau 60 phút). Mỗi request sau đó gửi `Authorization: Bearer <token>`, và `verify_token` giải mã, kiểm tra chữ ký và hạn rồi lấy ra `username`, `role`. Server không cần tra database mỗi request nên là stateless.

```text
# Sai mật khẩu
POST /auth/token {"username":"student","password":"x"}
HTTP/1.1 401 Unauthorized   {"detail":"Invalid credentials"}

# Không có token
POST /ask
HTTP/1.1 401 Unauthorized   {"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Token giả
POST /ask  -H "Authorization: Bearer abc.def.ghi"
HTTP/1.1 403 Forbidden      {"detail":"Invalid token."}

# Token thật (đã che token)
POST /ask  -H "Authorization: Bearer eyJhbGciOiJI...<masked>"
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent ...","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Algorithm:** Sliding Window Counter (dòng 7–10). Mỗi user có một `deque` chứa timestamp, các mốc cũ hơn 60 giây bị loại, và nếu số mốc còn lại ≥ giới hạn thì trả 429.
- **Limit:** user **10 request/phút**, admin **100 request/phút** (dòng 86–87).
- **Bypass cho admin:** `app.py` dòng 141 chọn `rate_limiter_admin` khi `role == "admin"`. Đây là giới hạn cao hơn (100/phút), không phải không giới hạn.
- **Điểm yếu:** state nằm trong RAM của từng process, nên chạy nhiều instance hay restart thì bộ đếm bị mất hoặc chia nhỏ. Part 6 yêu cầu chuyển sang Redis.

Vòng lặp curl 14 lần với token `student` (đã dùng 1 request ở bước 4.2 trước đó, nên request thứ 10 trong vòng lặp là request thứ 11 trong cửa sổ 60 giây):

```text
req 1..9 : HTTP/1.1 200 OK
req 10   : HTTP/1.1 429 Too Many Requests
req 11..14: HTTP/1.1 429 Too Many Requests

Header của lần 429:
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795597131
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard (`cost_guard.py`)

**Cách làm của file có sẵn:** (tôi đọc và chạy thử, không tự viết lại)
- Mỗi lần `/ask`, `check_budget(user)` chạy **trước** khi gọi LLM, và `record_usage(user, in_tokens, out_tokens)` chạy **sau** khi gọi xong.
- Chi phí tính theo token: `input/1000 × 0.00015 + output/1000 × 0.0006` (giá GPT-4o-mini).
- Có hai tầng: ngân sách mỗi user **$1/ngày** (vượt thì **402**) và ngân sách toàn cục **$10/ngày** (vượt thì **503**). Khi dùng ≥ 80% thì ghi cảnh báo vào log.
- Bộ đếm theo ngày (`time.strftime("%Y-%m-%d")`): sang ngày mới thì `_get_record` tạo record mới nên tự reset.

Với `student`, một request chỉ tốn khoảng $0.00002, nên không thể chạm $1 bằng tay. Để tự thấy 402, tôi tạo `CostGuard(daily_budget_usd=0.0005)` và gọi liên tiếp:

```text
call 1: ok, spent=$0.00045
call 2: ok, spent=$0.0009
call 3: HTTP 402 {'error': 'Daily budget exceeded', 'used_usd': 0.0009, 'budget_usd': 0.0005, 'resets_at': 'midnight UTC'}
```

**Hạn chế và hướng làm ở Part 6:** `CostGuard` lưu trong RAM (`_records` là dict), nên mất khi restart và không dùng chung giữa các instance. Ở Part 6 tôi sẽ lưu chi phí trong Redis (khóa theo ngày hoặc tháng, `INCRBYFLOAT`, đặt TTL để tự reset) và trả 402 khi vượt `DAILY_BUDGET_USD`.

**Quan sát thêm:** trường `budget_remaining_usd` trong response của `/ask` thực ra trả về `usage.total_cost_usd` (số đã tiêu, `1.9e-05`), không phải số còn lại. Đây là lỗi đặt tên trong code mẫu, và tôi không sửa vì bài này chỉ yêu cầu đọc và chạy.

**Cần hiểu (CP3):** rate limit bảo vệ **tốc độ** (một client không gọi dồn dập làm quá tải hay brute-force), còn cost guard bảo vệ **tiền** (kể cả khi từng client gọi chậm, tổng chi phí LLM vẫn có trần). Chỉ có rate limit thì nhiều user hoặc request đắt vẫn làm cháy ngân sách. Chỉ có cost guard thì một client có thể làm nghẽn dịch vụ trước khi chạm trần tiền.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

Bản develop đã có sẵn hai endpoint (tôi đọc và chạy, không tự viết lại):

- **`GET /health` (liveness, dòng 104–144):** trả 200 kèm `status`, `uptime_seconds`, `version` và kết quả kiểm tra bộ nhớ (psutil). Nếu endpoint này không trả 200 hoặc timeout thì nền tảng restart container.
- **`GET /ready` (readiness, dòng 147–168):** trả 200 khi cờ `_is_ready` đã bật (sau khi startup xong), và **503** khi đang khởi động hoặc đang shutdown. Load balancer dùng nó để quyết định có route traffic vào instance hay không.

```text
GET /health -> HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":4.7,"version":"1.0.0","environment":"development","timestamp":"...","checks":{"memory":{"status":"ok","used_percent":12.8}}}

GET /ready  -> HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

**Liveness khác readiness ở đâu:** liveness hỏi "process còn sống không?", và nếu không thì **restart** nó. Readiness hỏi "đã sẵn sàng nhận traffic chưa?", và nếu chưa thì **ngừng gửi request** tới nó nhưng không restart. Một instance đang khởi động hoặc mất kết nối Redis nên là "sống nhưng chưa sẵn sàng". Nếu gộp hai thứ làm một, mất Redis sẽ khiến nền tảng restart cả đàn instance không cần thiết. Vì vậy ở Part 6, `/health` phải trả 200 kể cả khi Redis chết, còn `/ready` phải trả 503.

### Exercise 5.2: Graceful shutdown

Cơ chế trong file: middleware `track_requests` đếm request đang xử lý (`_in_flight_requests`), phần shutdown của `lifespan` đặt `_is_ready = False` rồi chờ tối đa 30 giây cho tới khi số request đang xử lý về 0, và `uvicorn.run(..., timeout_graceful_shutdown=30)`. Handler `handle_sigterm` chỉ ghi log, còn việc tắt gọn do uvicorn làm.

**Thí nghiệm:** bắn 20 request song song vào `/ask`, rồi gửi `kill -TERM` ngay lập tức.

```text
Kết quả 20 request:   3 x HTTP 200     17 x 000 (không kết nối được)

Log server:
INFO:     Shutting down
INFO:     ... "POST /ask?question=Long%20task%202 HTTP/1.1" 200 OK
INFO:     ... "POST /ask?question=Long%20task%203 HTTP/1.1" 200 OK
INFO:     Waiting for connections to close. (CTRL+C to force quit)
INFO:     ... "POST /ask?question=Long%20task%201 HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
... INFO 🔄 Graceful shutdown initiated...
... INFO ✅ Shutdown complete
INFO:     Finished server process
Process còn sống sau đó? no
```

**Giải thích:** 3 request đã được server nhận trước SIGTERM đều hoàn thành với 200 và không có request nào bị cắt giữa chừng (log chỉ có 3 dòng `POST` và đều là 200). 17 request còn lại bắn quá sát lúc tắt nên chưa kịp kết nối, do server đã đóng cổng nghe và ngừng nhận kết nối mới. Đúng với hành vi mong muốn: **ngừng nhận mới, xử lý xong việc đang làm, rồi thoát.** Mock LLM chỉ trễ khoảng 0,1 giây nên rất khó bắt được request "đang dở", vì vậy con số 3/17 phụ thuộc vào thời điểm bắn và sẽ khác ở mỗi lần chạy.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

- **Anti-pattern:** giữ `conversation_history = {}` trong RAM của process. Khi chạy nhiều instance, mỗi instance có bộ nhớ riêng nên request 1 vào instance A còn request 2 vào instance B sẽ **không thấy** history. Restart cũng làm mất toàn bộ.
- **Cách bản production làm:** state nằm trong Redis. `save_session` ghi `session:<id>` bằng `SETEX` với TTL 3600 giây, `load_session` đọc lại, và `append_to_history` giữ tối đa 20 tin nhắn. Mọi instance đều đọc ghi cùng một Redis nên instance nào cũng phục vụ được bất kỳ session nào. Mỗi response có `served_by` để thấy rõ instance nào xử lý.
- **Lưu ý:** đầu file có fallback sang `_memory_store` (dict trong RAM) khi không kết nối được Redis, và response ghi rõ `"storage": "in-memory"`. Chế độ này là bẫy khi scale, vì lúc đó lại bị đúng lỗi phía trên. Ở Part 6, `/ready` phải trả 503 thay vì lặng lẽ chuyển sang bộ nhớ.

**Vì sao state trong RAM hỏng khi chạy nhiều instance:** mỗi instance là một process riêng với bộ nhớ riêng và load balancer chia request tùy ý, nên không có gì đảm bảo hai request liên tiếp của cùng một user vào cùng một instance. Điều này cũng giải thích vì sao rate limiter và cost guard ở Part 4 (đều lưu trong RAM) sẽ sai khi scale: mỗi instance đếm riêng, nên giới hạn thực tế thành `giới hạn × số instance`.

### Exercise 5.4: Load balancing

Theo README mục K5 số 5 và số 7: stack này mở cổng **8080**, endpoint là **`POST /chat`**, và dùng `-p` để khỏi trùng tên project.

```bash
cd 05-scaling-reliability/production && touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

```text
NAME                       SERVICE   STATUS
k5-day14-scaling-agent-1   agent     Up (healthy)   8000/tcp
k5-day14-scaling-agent-2   agent     Up (healthy)   8000/tcp
k5-day14-scaling-agent-3   agent     Up (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx     Up             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis     Up (healthy)   6379/tcp
```

Gọi 10 request qua Nginx (`POST /chat`), đếm theo `served_by`:

```text
  3 instance-0057d6
  4 instance-bb2946
  3 instance-e54d1a
```

Nginx chia đều (round-robin) cho 3 instance qua DNS `agent` của Docker. `nginx.conf` còn có `proxy_next_upstream error timeout http_503`, tức là nếu một instance lỗi hoặc trả 503 thì Nginx thử lại ở instance khác (tối đa 3 lần).

### Exercise 5.5: Test stateless

`python test_stateless.py` gửi 5 câu trong cùng một session (script không tự tắt instance nào, xem README mục K5 số 7):

```text
Session ID: a9b6d910-0072-43de-b54a-3082d947b3c0
Request 1: [instance-e54d1a]   Request 2: [instance-0057d6]   Request 3: [instance-bb2946]
Request 4: [instance-e54d1a]   Request 5: [instance-0057d6]
Instances used: {'instance-e54d1a', 'instance-0057d6', 'instance-bb2946'}
Total messages: 10   (5 user + 5 assistant)
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu đi qua cả 3 instance, nhưng history cuối cùng có đủ 10 tin nhắn theo đúng thứ tự, vì mọi instance đọc ghi chung Redis.

**Thí nghiệm thêm (CODE_LAB mô tả bước "kill instance"):** tôi dừng `k5-day14-scaling-agent-1` bằng `docker stop`, rồi gọi tiếp với cùng `session_id`:

```text
history count sau khi stop 1 instance: 10      (không mất gì)
4 request tiếp theo: vẫn trả 200, do 2 instance còn lại phục vụ (bb2946, e54d1a)
history count cuối: 18                           (10 + 4 câu x 2 tin nhắn)
```

Hội thoại vẫn liền mạch và không mất dữ liệu khi một instance chết. Xong bài tôi đã chạy `docker compose -p k5-day14-scaling down` để trả cổng 8080.

---

## Part 6: Final Project (`06-lab-complete/`)

### Kết quả `python check_production_ready.py` (chạy đầy đủ, có Docker, trong WSL2)

Python 3.11.18, `os.name = posix`. Phần "📋 Checklist Deliverable" của output:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số số đo từ cùng lần chạy: image **238 MB** (giới hạn 500 MB), build 33 giây, `docker stop` tắt trong **0,9 giây** với exit code 0, rate limit chặn sau đúng 5 request khi `RATE_LIMIT_PER_MINUTE=5`, 17 dòng log đều là JSON hợp lệ.

### Thiết kế và lý do (các điểm Lab Coach có thể hỏi)

| Tiêu chí | Cách làm | Vì sao |
|---|---|---|
| `/health` vs `/ready` | `/health` luôn 200. `/ready` ping Redis và trả **503** khi lỗi | Liveness chỉ hỏi process còn sống không. Nếu `/health` phụ thuộc Redis thì Redis chết sẽ khiến nền tảng restart cả agent, mà restart không sửa được Redis. `/ready` mới là chỗ báo "chưa nhận được traffic" để load balancer tạm bỏ instance |
| Redis client | `redis.from_url()` ở mức module, không ping lúc import, timeout 2 giây | App phải khởi động được khi Redis chưa sẵn sàng (container khởi động cùng lúc với Redis) |
| API key | `APIKeyHeader(auto_error=False)`, so sánh bằng `hmac.compare_digest`, thiếu hoặc sai đều **401** | Mặc định FastAPI trả 403 khi thiếu header. `compare_digest` tránh timing attack. Chưa đặt `AGENT_API_KEY` thì từ chối tất cả thay vì "mở cửa" |
| Rate limit | Sliding window bằng Redis sorted set (`ZREMRANGEBYSCORE` → `ZADD` → `ZCARD`) trong một transaction `MULTI/EXEC`. Vượt thì gỡ request vừa thêm và trả **429** kèm `Retry-After` | Một transaction tránh race giữa 2 worker uvicorn. State trong Redis nên vẫn còn sau restart và dùng chung giữa các instance (khác `rate_limiter.py` của Part 4 chỉ nằm trong RAM). Key trong Redis là bản băm SHA-256 của API key, không lưu key thô |
| Cost guard | Cộng dồn chi phí vào Redis bằng `INCRBYFLOAT` theo ngày (`cost:daily:YYYY-MM-DD`) và theo tháng (`cost:monthly:YYYY-MM`), có TTL. `check_budget()` trước LLM, `record_cost()` sau LLM, vượt ngưỡng nào trước thì trả **402** | Đổi ngày hoặc tháng thì sang key mới nên tự reset. Là giới hạn mềm: chi phí chỉ được cộng sau khi gọi LLM nên vài request chạy song song có thể cùng qua cổng kiểm tra |
| Cấu hình | `config.py` đọc env bằng `os.getenv`, `.env.example` liệt kê đủ biến, `.env` nằm trong `.gitignore` | 12-Factor: đổi cấu hình giữa môi trường mà không sửa code. Không có secret trong code |
| Log JSON | `JsonFormatter` tự viết (`json.dumps`), mỗi dòng một object (`ts`, `lvl`, `event`, các trường thêm). Stack trace nếu có chỉ vào log, đã escape thành một dòng | Dễ parse trong log aggregator. Không log API key |
| Lỗi | Handler cho `Exception` trả `500 {"detail":"Internal server error"}`, đầu vào sai trả 422 | Không lộ stack trace cho client |
| Graceful shutdown | **Không** tự đăng ký handler SIGTERM, để uvicorn xử lý (ngừng nhận kết nối mới, chờ request đang chạy xong, thoát với exit code 0). Dockerfile dùng `exec uvicorn` để uvicorn là PID 1 | Skeleton cảnh báo handler tự viết sẽ chặn mất handler của uvicorn khiến process không bao giờ thoát. Nếu CMD là dạng shell không có `exec` thì PID 1 là `sh`, không chuyển tiếp SIGTERM, và `docker stop` sẽ chờ hết 10 giây rồi SIGKILL (exit code 137) |
| Dockerfile | Multi-stage (builder cài dependencies vào `--prefix=/install`, runtime chỉ copy kết quả), `python:3.11-slim`, user non-root `appuser`, `HEALTHCHECK`, CMD theo `${PORT:-8000}` | Image nhỏ và không chứa công cụ build. `PORT` do Railway/Render cấp |
| Compose | `env_file` với `required: false`, `REDIS_URL=redis://redis:6379/0` đè lên `.env`, `depends_on` với `service_healthy` | Chạy được cả khi không có `.env`. Agent chỉ start sau khi Redis healthy |

### Tự kiểm tra thêm (ngoài script chấm)

Script chấm dùng chung một Redis tạm cho cả phiên, nên ở bước cost guard nó báo "402 ở request thứ 1": Redis đã có sẵn chi phí tích lũy từ các bước trước. Để chắc chắn cost guard đúng chứ không đạt nhờ trạng thái cũ, tôi chạy riêng trên Redis sạch với ngân sách $0.00005:

```text
req 1 -> 200   req 2 -> 200   req 3 -> 200
req 4 -> 402 {"detail":"Daily budget exceeded: $0.000060 of $5e-05 used."}
```

Request 3 vẫn qua dù đã sát ngưỡng, vì chi phí chỉ được cộng sau khi gọi LLM (giới hạn mềm, đúng như mô tả ở trên). Các kiểm tra khác trên agent chạy thật:

- Rate limit 3/phút: request 1–3 trả 200, request 4 và 5 trả 429 kèm `retry-after: 60`.
- Đầu vào sai: thiếu `question`, `question` rỗng, JSON hỏng đều trả **422**. Không có key trả **401**. Không lộ stack trace.
- Tắt Redis giữa chừng: `/health` vẫn **200**, `/ready` và `/ask` trả **503**.
- `docker compose up --build` với `.env` (key thử): `/health` 200, `/ready` 200, `/ask` không key 401, có key 200, container chạy bằng `appuser`, healthcheck `healthy`, `docker stop` 0,9 giây exit code 0.

### Gặp phải khi làm

- `requirements.txt` ghim `pydantic==2.9.0` không cài được trên Python 3.14 mặc định của WSL (không có wheel, phải build bằng Rust), mà script chấm chạy bằng interpreter cục bộ. Tôi tạo venv Python 3.11 bằng `uv` (`~/venv-lab06`) và giữ nguyên `requirements.txt`. Docker image vốn dùng Python 3.11 nên không bị ảnh hưởng.
- Tôi chạy `git status` trong WSL thì thấy gần như mọi file bị đánh dấu đã sửa. Đó chỉ là chênh lệch ký tự xuống dòng CRLF giữa Git của WSL và của Windows (`core.autocrlf=true`). Git của Windows chỉ liệt kê đúng các file tôi đã sửa. Vì vậy tôi commit bằng Git của Windows, không commit từ WSL.

---

## AI log

> Theo RULES.md mục 1: ghi mỗi lần dùng AI cho code Part 6 hoặc câu trả lời.

| Lần | Phần | Hỏi gì | Nhận gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | Part 1 | Đọc `develop/app.py`, `production/app.py`, `production/config.py` và chạy cả hai bản trong WSL để lấy bằng chứng cho mục Part 1 | Danh sách anti-pattern, output curl và bảng so sánh | Các số dòng và output curl đến từ lệnh chạy thật trên máy tôi (dòng 17, 18, 21, 33, 34, 51–53 của develop; `/health` 404; 422 và 200 như trên). **TODO của tôi:** đọc lại đối chiếu với file gốc trước khi nộp |
| 2 | Part 2 | Đọc hai Dockerfile, `docker-compose.yml`, `nginx.conf`; build hai image, chạy container và stack Compose trong WSL để lấy số đo | Câu trả lời Exercise 2.1, giải thích multi-stage, sơ đồ stack | Kích thước (1.67 GB, 240 MB), `whoami`, trạng thái healthy, output curl qua Nginx đều lấy từ lệnh chạy thật. **TODO của tôi:** đọc lại các Dockerfile để tự giải thích được từng câu trả lời |
| 3 | Part 4 | Đọc `develop/app.py`, `production/{app,auth,rate_limiter,cost_guard}.py`; chạy cả hai bản và vòng lặp curl trong WSL | Câu trả lời 4.1–4.4, output 401/403/200/429, thử 402 bằng `CostGuard` với ngân sách nhỏ | Output curl lấy từ lệnh chạy thật, token đã che. Tôi không tự viết lại cost guard, chỉ đọc và chạy thử mã có sẵn, và ghi rõ trong bài. **TODO của tôi:** đọc lại `rate_limiter.py` và `cost_guard.py` để tự giải thích được |
| 4 | Part 5 | Đọc `develop/app.py`, `production/{app.py,docker-compose.yml,nginx.conf,test_stateless.py}`; chạy health check, thí nghiệm SIGTERM, stack 3 instance và test stateless trong WSL | Câu trả lời 5.1–5.5 và các output | Output lấy từ lệnh chạy thật. Thí nghiệm SIGTERM phụ thuộc thời điểm bắn nên số 3/17 sẽ khác mỗi lần, và tôi đã ghi rõ trong bài. **TODO của tôi:** đọc lại `lifespan` và middleware đếm request để tự giải thích được |
| 5 | Part 6 | Đọc `check_production_ready.py` và các file khung; viết `config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `railway.toml`, `render.yaml` | Mã nguồn của toàn bộ Part 6; script chấm báo `PASS 12/12` ngay lần chạy đầu | Tôi chạy script chấm đầy đủ trong WSL (Docker thật, `os.name = posix`), rồi tự kiểm chứng thêm cost guard trên Redis sạch, rate limit theo từng key, lỗi đầu vào, Redis chết giữa chừng và `docker compose up` thật. Phát hiện script báo "402 ở request thứ 1" do Redis dùng chung giữa các bước nên tôi kiểm lại riêng (3 request 200 rồi 402). **TODO của tôi:** đọc lại từng file trong `06-lab-complete/app/` để tự giải thích được, nhất là `rate_limiter.py` (transaction Redis) và vì sao không tự đăng ký handler SIGTERM |
| 6 | Part 3 | Đọc `cloudbuild.yaml`, `service.yaml`; sửa `render.yaml` (đường dẫn Dockerfile), viết phần so sánh `railway.toml`/`render.yaml`, pipeline Cloud Run và `DEPLOYMENT.md`; hướng dẫn các bước deploy Render | Văn bản so sánh, mô tả pipeline, `DEPLOYMENT.md`; chẩn đoán lỗi 401 khi thử với key | Tôi tự deploy trên Render và chạy 4 lệnh kiểm tra bằng tài khoản và key của mình. AI chỉ chạy `check_production_ready.py --public-url` để xác nhận `/health` trả 200. **TODO của tôi:** chụp 3 ảnh trong `screenshots/` và đọc lại để tự giải thích sự khác nhau giữa hai file cấu hình |
