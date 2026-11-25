# Benchmark & Observability Report — Day 14

> Mọi con số trong file này lấy từ các file JSON trong `reports/` (và CSV trong `benchmark-results/` ở CP8), do chính các lệnh trong CHECKPOINTS chạy ra.
> Mỗi cấu hình chỉ chạy **một lần** với 300 request, nên các con số dao động giữa các lần chạy (xem mục *Giới hạn của phép đo*).

**Họ tên:** LeHoangSon (2A202603662)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + WSL2 (Ubuntu 26.04), 12 CPU logic (Intel i5-11400H) và khoảng 7,8 GB RAM cấp cho WSL, Docker Desktop (Docker 29.9.3), Python 3.11.18. Agent và công cụ load test chạy **cùng một máy**, giao tiếp qua `localhost`.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Ở tải bình thường (concurrency 1–50) agent đo được p95 khoảng 220–236 ms, nên ngưỡng 500 ms chừa khoảng gấp đôi để chịu dao động. Ngưỡng này đủ chặt để bắt được sự cố thật: ở concurrency 100 p95 đo được 3343 ms và vi phạm, còn khi 10% request chậm p95 là 1689 ms cũng vi phạm |
| Error rate `/ask` | < 2 % | Mock LLM cố tình lỗi 1% request (`MOCK_ERROR_RATE`), nên 1% là mức nền không tránh được. Đặt SLO bằng 1% sẽ vi phạm liên tục chỉ vì dao động ngẫu nhiên, còn 2% (gấp đôi mức nền) chừa error budget mà vẫn bắt được sự cố |
| Accuracy trên golden dataset | ≥ 95 % | Golden dataset có 23 câu, nên 95% tương đương cho phép sai tối đa 1 câu (22/23 = 95,7%). Sai 2 câu (91,3%) thì không đạt. Với tập nhỏ như vậy, mỗi câu sai đã làm accuracy giảm 4,3 điểm % |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Cấu hình: agent v2 chạy bằng `python app.py` (một process uvicorn), 300 request mỗi lần, `MOCK_SLOW_RATE` mặc định 0,03, SLO của công cụ là p95 ≤ 500 ms và error rate ≤ 2%. Dữ liệu: `reports/load_v2_c{1,10,50,100}.json`.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4,06 | 191,0 | 223,1 | 1703,6 | 0,00% | PASS |
| 10 | 37,21 | 190,1 | 221,1 | 1691,7 | 1,00% | PASS |
| 50 | 112,08 | 194,3 | 235,7 | 1707,2 | 1,00% | PASS |
| 100 | 72,95 | 390,3 | 3343,3 | 3694,2 | 3,33% | **FAIL** (p95 và error rate) |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency, và tới mức 100 còn **giảm**.

- **Từ 1 lên 10:** RPS tăng 9,2 lần (4,06 → 37,21), gần tuyến tính. Điều này hợp lý vì latency mỗi request gần như không đổi (p50 khoảng 190 ms), mà mỗi request chủ yếu là chờ `sleep` của mock LLM chứ không tốn CPU. Theo công thức throughput ≈ concurrency / latency, 10 / 0,231 s ≈ 43 req/s lý thuyết, đo được 37.
- **Từ 10 lên 50:** RPS chỉ tăng 3 lần (37 → 112) trong khi concurrency tăng 5 lần. Một phần vì run quá ngắn (300 request chỉ chạy 2,68 s), mà **một** request chậm 1,7 s đã chiếm hơn một nửa thời gian của cả lần chạy, làm RPS bị kéo xuống. Con số RPS ở mức này kém ổn định.
- **Ở 100:** p50 tăng gấp đôi (194 → 390 ms), p95 vọt lên 3343 ms và RPS giảm còn 73. Request bắt đầu **xếp hàng** thay vì được xử lý song song, đây là dấu hiệu bão hòa. Error rate lên 3,33% (10 lỗi 503), nhưng lỗi 503 ở đây do mock LLM tự sinh (1% mức nền) và dao động ngẫu nhiên, nên tôi không kết luận được nó có tăng thật do tải hay không.
- **Nút thắt:** chưa xác định được. Agent chạy **một** process uvicorn (một event loop) và công cụ load test cùng chạy trên máy này nên tranh CPU với nó. Tôi không profile nên không biết nghẽn nằm ở server hay ở phía client. Để kết luận cần chạy load test từ máy khác hoặc dùng nhiều worker và so sánh.

### 2.2 Tail latency

Cấu hình: v2, 300 request, concurrency 20, restart agent với từng giá trị `MOCK_SLOW_RATE`. Dữ liệu: `reports/load_v2_slow_{0,0.03,0.1}.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192,0 | 217,3 | 223,1 |
| 0.03 (mặc định) | 230,8 | 220,8 | 1705,3 |
| 0.1 | 338,5 | 1688,6 | 1708,0 |

**Nhận xét:**

- **Chỉ số nhạy nhất là p99.** Chỉ với 3% request chậm, p99 tăng từ 223 lên 1705 ms (gấp 7,6 lần), trong khi p95 gần như không đổi (217 → 221 ms) và avg chỉ tăng 20%. Khi tỉ lệ chậm lên 10% thì tới lượt p95 cũng vọt lên (1689 ms), còn avg tăng 76% (338 ms).
- **Vì sao avg tăng ít còn p99 tăng vọt:** avg là trung bình nên mỗi request chậm chỉ đóng góp một phần nhỏ. Mức tăng của avg xấp xỉ `tỉ lệ chậm × độ chậm thêm`: 0,03 × 1500 ms = 45 ms (đo được +38,8) và 0,1 × 1500 = 150 ms (đo được +146,5). Percentile thì nhìn vào **đuôi**: khi số request chậm vượt 1% (với p99) hoặc 5% (với p95) của tổng, percentile đó nhảy hẳn sang giá trị của nhóm chậm.
- **Vì sao SLO không nên đặt theo average:** ở `MOCK_SLOW_RATE=0.1`, avg là 338 ms, **vẫn dưới 500 ms** và trông ổn, nhưng cứ 10 người dùng thì 1 người phải chờ khoảng 1,7 giây. Chỉ số trung bình che mất nhóm người dùng đó. Percentile (p95/p99) phản ánh trải nghiệm của nhóm chậm nhất nên SLO phải đặt theo chúng.
- **Lưu ý về error rate:** cột error rate là 1,00% / 1,00% / 2,33%. Tỉ lệ lỗi do `MOCK_ERROR_RATE` (cố định 1%) quyết định, không liên quan tới `MOCK_SLOW_RATE`. Con số 2,33% (7 lỗi trong 300 request) chỉ là dao động ngẫu nhiên quanh kỳ vọng 3 lỗi, nên không được hiểu là "request chậm gây ra nhiều lỗi hơn".

### Giới hạn của phép đo

- Mỗi cấu hình chạy **một lần**, 300 request. Với `MOCK_SLOW_RATE=0,03` chỉ có khoảng 9 request chậm mỗi lần chạy, nên p99 phụ thuộc vào đúng vài request đó và sẽ thay đổi giữa các lần chạy. Mốc 300 request cũng quá ít để RPS ở concurrency cao ổn định.
- Agent và load test cùng một máy, nên số đo gồm cả tranh chấp tài nguyên giữa hai bên.
- Latency ở đây là của mock LLM (chủ yếu là `sleep`), không phản ánh LLM thật.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Golden dataset 23 câu, câu đúng khi có ≥ 60% keyword mong đợi. Dữ liệu: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,3% (1/23) | 91,3% (21/23) | **100%** (23/23) |
| Avg tokens / câu | 56,8 | 109,0 | 114,7 |
| Tổng cost (USD) | 0,0004 | 0,000759 | 0,000799 |
| Cost / câu đúng (USD) | 0,00040035 | 0,00003616 | 0,00003475 |
| Quality gate | FAIL | PASS | PASS |

Quality gate mỗi lần dùng ngưỡng khác nhau, nên cần đọc kèm ngưỡng: v1 và v2 dùng `--min-accuracy` mặc định 0,8 (v1 FAIL vì 4,3% < 80%, v2 PASS vì 91,3% ≥ 80% và không có regression so với v1). Lần chạy cuối dùng `--min-accuracy 1.0` và `--baseline reports/eval_v2.json`, PASS với 0 regression.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key") | `token`, `hết hạn`, `chữ ký` | Câu trả lời của v2 là câu chung chung ("Câu hỏi hay! Điều này phụ thuộc vào kiến trúc..."), vì `KNOWLEDGE_BASE` không có tài liệu nào khớp. Thêm entry với từ khoá `jwt` và nội dung có đủ 3 keyword trên (JWT là token có chữ ký số, có thời điểm hết hạn) |
| `scaling-03` ("Kubernetes HPA scale dựa trên chỉ số nào") | `cpu`, `memory`, `custom metrics` | Cùng nguyên nhân. Thêm entry với từ khoá `hpa`, `kubernetes`, `autoscal` và nội dung nêu CPU, memory, custom metrics |

Hai từ khoá kích hoạt được chọn hẹp nên không làm đổi retrieval của các câu khác. Kết quả xác nhận: eval sau khi sửa có **2 câu được cải thiện và 0 regression**. Tôi chỉ sửa `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py`, không sửa `golden_dataset.jsonl` (RULES.md mục 3).

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng tăng rất mạnh:** từ 4,3% lên 91,3% (v2 chưa sửa), tức 20 câu được cải thiện và không câu nào tệ đi.
- **Chi phí mỗi câu tăng:** v2 tốn 109,0 token mỗi câu so với 56,8 của v1 (gấp 1,9 lần) vì prompt có thêm tài liệu retrieval, nên tổng cost cũng tăng (0,000759 so với 0,0004 USD).
- **Nhưng chi phí cho mỗi câu ĐÚNG lại giảm mạnh:** v1 tốn 0,00040035 USD cho 1 câu đúng, v2 chỉ 0,00003616, tức **rẻ hơn khoảng 11 lần**. Lý do là v1 trả tiền cho 22 câu sai. Vì vậy so hai phiên bản bằng cost / câu sẽ cho kết luận ngược (v2 "đắt hơn"), còn cost / câu đúng mới phản ánh đúng giá trị.
- **Latency:** thêm bước retrieval (khoảng 20 ms mỗi request trong mock), nhưng ở eval chỉ có 23 mẫu nên cột latency p95 không đáng tin (p95 của v1 và v2 chưa sửa đều ~1500 ms chỉ vì mỗi lần có một request chậm). README đã cảnh báo: latency phải đo bằng load test chứ không phải bằng eval.

### Quality gate trong CI: dùng exit code để chặn merge

`run_eval.py` trả **exit code 1** khi accuracy thấp hơn `--min-accuracy` hoặc có regression so với `--baseline`, và 0 khi đạt. CI chỉ cần chạy lệnh đó, vì bước nào trả mã khác 0 thì job fail và (nếu bật branch protection yêu cầu job này pass) PR không merge được.

Bằng chứng từ chính lần chạy của tôi: eval agent v1 với `--baseline reports/eval_v2.json` (giả lập một thay đổi làm chất lượng tụt) cho **20 câu bị regression**, `Quality gate ... ❌ FAIL` và **exit code 1**.

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Run agent + eval
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

`MOCK_ERROR_RATE=0` để lỗi ngẫu nhiên của mock không làm job đỏ nhầm. Muốn phát hiện regression thì thêm `--baseline` trỏ tới report của nhánh `main`. Việc chặn merge thật sự còn cần bật *Branch protection → Require status checks to pass* cho job `quality-gate` trong cài đặt repo GitHub.

### Phụ lục: Exercise 7.1 (metrics)

- **Mỗi loại metric:** Counter `http_requests_total{method="POST",route="/ask",status="200"}`, Gauge `agent_in_flight_requests` (và `agent_info`), Histogram `http_request_duration_seconds_bucket{le="0.2",...}`.
- **Vì sao label `route` dùng `route.path` (template) thay vì `request.url.path`:** tôi đã thử gọi `/wp-admin`, `/.env`, `/a1b2c3` thì cả ba được gom vào một series `route="unmatched"` (`http_requests_total{...,route="unmatched",status="404"} 3.0`). Nếu dùng URL thật, mỗi URL lạ tạo ra một series riêng, bot quét hàng nghìn URL sẽ sinh hàng nghìn time series (cardinality bùng nổ) làm Prometheus tốn RAM. Hơn nữa nó còn là cách để kẻ tấn công làm hỏng hệ thống giám sát.
- **Nhiệm vụ:** đã thêm Histogram `agent_question_length_chars` (buckets 20, 50, 100, 200, 500, 1000, 2000) vào `develop/app.py` và gọi `observe(len(body.question))` trong `ask()`. Kiểm tra: sau một request câu hỏi 40 ký tự, `/metrics` có `agent_question_length_chars_count 1.0` và `agent_question_length_chars_sum 40.0`. Dùng Histogram chứ không dùng label vì độ dài có vô số giá trị.

---

## 4. Observability stack (production)

> Làm ở CP8 (sau giờ lab).

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
