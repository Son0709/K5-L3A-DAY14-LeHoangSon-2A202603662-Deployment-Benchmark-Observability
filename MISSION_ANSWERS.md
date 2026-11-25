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

## AI log

> Theo RULES.md mục 1: ghi mỗi lần dùng AI cho code Part 6 hoặc câu trả lời.

| Lần | Phần | Hỏi gì | Nhận gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | Part 1 | Đọc `develop/app.py`, `production/app.py`, `production/config.py` và chạy cả hai bản trong WSL để lấy bằng chứng cho mục Part 1 | Danh sách anti-pattern, output curl và bảng so sánh | Các số dòng và output curl đến từ lệnh chạy thật trên máy tôi (dòng 17, 18, 21, 33, 34, 51–53 của develop; `/health` 404; 422 và 200 như trên). **TODO của tôi:** đọc lại đối chiếu với file gốc trước khi nộp |
