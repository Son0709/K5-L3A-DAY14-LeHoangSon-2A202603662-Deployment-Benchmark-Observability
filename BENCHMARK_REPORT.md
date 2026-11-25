# Benchmark & Observability Report — Day 14

> Mọi con số trong file này lấy từ các file JSON trong `reports/` (và CSV trong `benchmark-results/` ở CP8), do chính các lệnh trong CHECKPOINTS chạy ra.
> Mỗi cấu hình chỉ chạy **một lần** với 300 request, nên các con số dao động giữa các lần chạy (xem mục *Giới hạn của phép đo*).

**Họ tên:** Lê Hoàng Sơn (2A202603662)
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

Stack Docker Compose (`-p k5-day14-observability`): 2 agent, Nginx, Prometheus, Grafana, Jaeger, Locust. `promtool test rules prometheus/alert_rules_test.yml` báo `SUCCESS`. `GET /metrics` qua Nginx (cổng 8080) trả **404**, còn Prometheus scrape trực tiếp trong mạng nội bộ. Tải nền khi làm thí nghiệm: Locust headless 10 user.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải và có sự cố: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (span chậm nhất `chat mock-llm-small`, 1683 ms): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 2 alert đang **firing** (`AgentHighErrorRate` và `AgentInstanceDown`): [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

### 4.2 Thí nghiệm "phá hệ thống"

Thời gian tính từ lúc chạy lệnh `docker compose up -d` với cấu hình mới (hoặc `docker pause` ở thí nghiệm D) đến lúc alert chuyển trạng thái, đo bằng cách hỏi API `/api/v1/alerts` của Prometheus mỗi 3 giây (sai số khoảng ±3 giây). Mỗi thí nghiệm chỉ chạy **một lần**. Cấu hình `for` của các rule: `AgentHighErrorRate` 1 phút, `AgentHighLatencyP95` 2 phút, `AgentInstanceDown` 30 giây, `LLMCostBurnRateHigh` 2 phút.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending sau 30 s, **firing sau 90 s** (error rate đo được 21–23%) | **Error rate** (ô thống kê chuyển đỏ, 22,53% trong ảnh) và "Requests/s theo status code" (đường 503 tăng) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending sau 27 s, **firing sau 147 s** | Biểu đồ "Latency /ask" (p95/p99 vọt lên, avg tăng ít hơn) và ô **Latency p95** |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | pending sau 56 s, **firing sau 176 s** | "Cost burn rate (USD/giờ)" và ô **LLM cost (1h)** |
| D | `docker pause` 1 instance (A đang chạy) | `AgentInstanceDown` | pending sau 10 s, **firing sau 40 s** | Ô **Instances up** (giảm còn 1) và "Requests/s theo instance" (một instance ngừng nhận traffic) |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | không áp dụng | Chỉ thấy ở metric chất lượng, xem phân tích bên dưới |

**Mức độ chắc chắn của cột "panel":** với A và D tôi đối chiếu trực tiếp từ ảnh Grafana (Error rate đỏ, Instances up = 1, một đường instance rơi xuống). Với B, C, E tôi **không chụp panel lúc đó**, nên cột này suy ra từ câu truy vấn của từng panel và từ rule alert, chưa quan sát bằng mắt. Thời gian firing thì đo thật, không suy ra.

**Những điều cần biết khi đọc số liệu:**
- Mỗi lần đổi cấu hình, các container agent bị tạo lại nên `AgentInstanceDown` chuyển `pending` khoảng 3–6 giây rồi tự tắt, không bao giờ firing vì chưa đủ 30 giây. Đây là nhiễu của cách làm thí nghiệm, không phải sự cố thật.
- Trước khi đổi cấu hình ở B, `AgentHighLatencyP95` đang `pending` (sau thí nghiệm E, khi agent vừa được khôi phục). Tôi **chưa kiểm chứng nguyên nhân**; giả thuyết hợp lý nhất là ngay sau khi khởi động lại, cửa sổ 1 phút có rất ít request nên chỉ một request chậm cũng đẩy p95 vượt 1 giây. Alert đó biến mất khi agent được tạo lại, và `pending` mới bắt đầu lúc 15:26:02 UTC, khớp với tác động của B, nên số đo 147 giây vẫn dùng được. Dù nguyên nhân là gì, hiện tượng này cho thấy alert p95 có thể báo giả ở giai đoạn traffic thấp.
- Thí nghiệm D đo khi A vẫn đang chạy, để có hai alert cùng firing cho một ảnh chụp. Hai alert độc lập nhau nên không ảnh hưởng thời gian của D.
- Thí nghiệm C còn làm `AgentHighLatencyP95` chuyển `pending` ngắn rồi tắt (model lớn có latency cao hơn 2,5 lần), không firing.

**Thí nghiệm D: vì sao dùng `docker pause`, và vì sao lỗi 504 không hiện trên dashboard agent.** Container bị `pause` vẫn còn trong DNS của Docker nhưng không trả lời, nên Prometheus thấy `up == 0` (target `172.18.0.6:8000` báo `context deadline exceeded`). Nếu `docker stop` thì container biến mất khỏi DNS, Prometheus coi như target không còn tồn tại chứ không phải "down", và không có alert. Trong lúc agent bị pause, log Nginx ghi **12 lỗi 504** (`upstream timed out ... while reading response header`), nhưng p95 phía agent vẫn chỉ **0,29 s**, vì những request đó chưa bao giờ được agent xử lý xong nên metric của agent không đếm chúng. Metric chỉ phản ánh những gì chính service đó nhìn thấy, vì vậy production cần giám sát cả ở tầng load balancer.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Chất lượng giảm nhưng hạ tầng vẫn khoẻ (latency và error rate không đổi), nên alert hạ tầng không bắt được. Bằng chứng từ chính lần chạy của tôi: sau khi đổi sang v1, eval qua Nginx (`run_eval.py --url http://localhost:8080`) cho **accuracy 4,3% (1/23), quality gate FAIL**, trong khi không có alert nào firing. Cách phát hiện:
1. **Chạy eval trên golden dataset định kỳ** với môi trường thật hoặc canary (không chỉ trong CI trước khi merge), và alert khi accuracy tụt dưới ngưỡng.
2. **Theo dõi các metric chất lượng gián tiếp.** Trong E, các tín hiệu đã thay đổi rõ: series `agent_retrieval_total` (retrieval hit/miss) **biến mất hoàn toàn** vì v1 không có retrieval (trước đó hit 5,69/s, miss 0,53/s), nhãn `agent_info{version}` đổi từ `v2` sang `v1`, và số token vào mỗi request giảm từ khoảng 74 xuống khoảng 36 (465 token/s ÷ 6,25 req/s so với 217 token/s ÷ 5,98 req/s; số v1 đo khi mới khởi động lại khoảng 80 giây nên chỉ mang tính tham khảo). Có thể đặt alert "retrieval hit ratio giảm bất thường".
3. **Lấy mẫu câu trả lời thật để chấm** (LLM-as-judge hoặc người duyệt) và thu phản hồi của người dùng (like/dislike, báo cáo sai).

### 4.3 Debug bằng trace

Trace chậm nhất tìm được (trong 400 trace gần nhất lấy từ Jaeger, có 7 trace trên 1 giây):

- `trace_id`: `ee7529a04e0209be00add43857fba24a`
- Tổng thời gian: **1709,3 ms**
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1683,2 ms, 98,5%**). Các span còn lại: `agent.run` 1707,2 ms (chứa các span con), `agent.retrieve_context` 23,6 ms (1,4%)
- Kết luận: chậm do **LLM upstream**, không phải code của agent (bước retrieval chỉ 23,6 ms)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T15:21:48.313160+00:00", "level": "INFO", "service": "observable-agent", "instance": "c11c87a578ae", "event": "llm_call", "trace_id": "ee7529a04e0209be00add43857fba24a", "span_id": "8898cad63be68992", "request_id": "9568bac93de7", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 73, "output_tokens": 35, "cost_usd": 3.2e-05, "llm_ms": 1681.6}
{"ts": "2026-11-25T15:21:48.313534+00:00", "level": "INFO", "service": "observable-agent", "instance": "c11c87a578ae", "event": "http_request", "trace_id": "ee7529a04e0209be00add43857fba24a", "span_id": "8898cad63be68992", "request_id": "9568bac93de7", "method": "POST", "route": "/ask", "status": 200, "ms": 1708.6}
```

Trace lỗi: `trace_id` `fb88c6a0cb34e4ccd2a6bda274202bd0`, tổng 95,6 ms, trả **503**. Span `chat mock-llm-small` (72,8 ms) có trạng thái lỗi, `error.type = upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`). Log tương ứng:

```json
{"ts": "2026-11-25T15:21:58.954019+00:00", "level": "INFO", "service": "observable-agent", "instance": "c11c87a578ae", "event": "llm_error", "trace_id": "fb88c6a0cb34e4ccd2a6bda274202bd0", "span_id": "7aa29c65a2c46753", "request_id": "3df4fdd6ff74", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Nhờ `trace_id` có trong cả log lẫn Jaeger, từ một dòng log có thể nhảy sang đúng trace (và ngược lại).

### 4.4 Trả lời câu hỏi Exercise 7.4

Số đo lấy từ Prometheus sau khi hệ thống ổn định (agent chạy hơn 4 phút, tải 10 user, 2 instance, cửa sổ 1 phút).

1. **p95 và avg:** p95 = **0,291 s**, avg = **0,226 s**, p50 = 0,171 s, p99 = **1,812 s**. p95 và avg gần nhau (chênh khoảng 65 ms) nên phần lớn request có latency tương đương nhau. Khoảng cách thật nằm ở p99: gấp khoảng 8 lần avg, do 3% request bị chậm bất thường (+1,5 s). Avg che mất đuôi này, đúng như đã thấy ở mục 2.2.
2. **Requests/s theo instance:** 3,02 và 3,13 req/s (49,1% và 50,9%), nên Nginx chia **đều** theo round-robin. Khi gọi 12 request bằng tay qua Nginx, header `X-Served-By` cũng chia 6 và 6.
3. **Vì sao input tokens/s lớn hơn output tokens/s:** input là **451** token/s, output là **238,5** token/s (gấp khoảng 1,9 lần). Prompt gửi cho LLM gồm system prompt, tài liệu truy xuất được (agent v2) và câu hỏi, còn câu trả lời thì ngắn hơn nhiều.
4. **`curl http://localhost:8080/metrics`:** trả **404 Not Found**. `nginx.conf` có `location = /metrics { return 404; }` vì metric lộ thông tin hệ thống (route, lưu lượng, version), nên chỉ Prometheus được scrape trực tiếp trong mạng nội bộ Docker, không public ra ngoài.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Cấu hình: `docker compose run --rm locust ... --headless -u 100 -r 10 -t 2m`, ramp 10 user mỗi giây, qua Nginx, agent v2, `MOCK_ERROR_RATE=0,01`, `MOCK_SLOW_RATE=0,03`. Số liệu của endpoint `/ask` (dòng `/ask` trong `benchmark-results/scale_{1,3}_stats.csv`). Locust báo exit code 1 vì có request lỗi, điều này bình thường do mock cố tình lỗi 1%.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59,96 | 190 | 230 | 1700 | 72 / 7161 (1,01%) |
| 3 | 60,22 | 190 | 230 | 1700 | 75 / 7204 (1,04%) |

(Cả hai lần RPS tổng gồm cả `/health` là 66,03 và 66,01.)

**Giải thích kết quả:** scale từ 1 lên 3 instance **không cải thiện gì**: RPS, p50, p95 và p99 gần như y hệt, và tỉ lệ lỗi vẫn khoảng 1% (đó là lỗi mock sinh ra, không liên quan số instance).

- **Throughput bị khống chế bởi mô hình tải, không phải bởi agent.** Mỗi user của Locust nghỉ trung bình 1,25 s (`between(0.5, 2)`) giữa các request. Một chu kỳ của user mất khoảng 1,25 + 0,22 (latency) = 1,47 s, nên 100 user chỉ tạo tối đa khoảng 100 / 1,47 ≈ **68 req/s**, và đo được 66,0 req/s (khoảng 97%, phần hụt là thời gian ramp-up 10 giây đầu). Nghĩa là 1 agent đã đủ xử lý toàn bộ tải này, và instance thứ 2, thứ 3 chỉ ngồi rảnh. Số request đang xử lý cùng lúc (in-flight) mà tôi thấy trong lúc làm chỉ khoảng 2–4, không có dấu hiệu bão hòa.
- **Latency không phụ thuộc số instance.** Mỗi request tốn khoảng 190 ms chủ yếu là thời gian chờ của mock LLM, và thêm instance không làm lệnh gọi LLM nhanh hơn. Còn p99 = 1700 ms là do 3% request chậm bất thường (+1,5 s) của mock, không phải do agent quá tải. Biểu đồ "LLM latency" trên Grafana cho thấy đúng các cú nhảy đó.
- **Nút thắt nằm ở đâu:** ở **LLM upstream** (latency quyết định p95/p99) và ở **mô hình tải** (số user và thời gian nghỉ quyết định RPS), không phải ở năng lực của agent.
- **Giới hạn của kết luận:** tôi **chưa tìm được điểm mà 1 instance bắt đầu bão hòa**, nên chưa chứng minh được khi nào scale ngang mới có ích. Muốn thấy lợi ích của scale cần tải lớn hơn năng lực 1 instance (nhiều user hơn, hoặc bỏ thời gian nghỉ). Mỗi mức chỉ chạy một lần 2 phút, và Locust cùng stack chạy chung một máy. Mỗi agent bị giới hạn 0,5 CPU và 256 MB, tôi không đo mức dùng CPU nên không kết luận được về CPU.
- **Một kết quả phụ:** chính tải 100 user này đã làm alert `LLMCostBurnRateHigh` chuyển `pending` rồi firing (chi phí ước tính vượt 2 $/giờ), tức là ngưỡng chi phí đó thấp so với mức tải này.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Phải nhìn percentile chứ không nhìn trung bình.** Ở `MOCK_SLOW_RATE=0,1`, avg chỉ 338 ms (dưới SLO 500 ms) nhưng p95 là 1689 ms: cứ 10 người dùng thì 1 người chờ khoảng 1,7 giây. Trên dashboard, p99 (1,8 s) gấp 8 lần avg (0,23 s) ngay cả khi hệ thống "khoẻ".
  2. **Một dashboard toàn xanh vẫn có thể che sự cố chất lượng hoặc sự cố ở tầng ngoài.** Đổi sang v1 làm accuracy tụt từ 100% xuống 4,3% mà không alert nào kêu, và 12 lỗi 504 ở Nginx không hề hiện trong metric của agent (p95 agent vẫn 0,29 s). Mỗi lớp quan sát chỉ thấy phần của nó: cần eval cho chất lượng và giám sát ở load balancer cho tầng mạng.
  3. **Scale ngang không tự động làm hệ thống nhanh hơn.** Thêm 3 instance không đổi RPS hay p95, vì giới hạn nằm ở mô hình tải và ở LLM upstream. Phải xác định nút thắt (qua metric và trace) trước khi tốn tiền thêm bản sao.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  - **Giám sát tầng load balancer:** tỉ lệ 5xx và 504 của Nginx, cộng một **synthetic probe** gọi từ bên ngoài (kiểu blackbox) để bắt lỗi mà metric của agent không thấy.
  - **Chất lượng:** chạy eval định kỳ trên môi trường thật và alert khi accuracy giảm; alert khi retrieval hit ratio tụt, và khi đổi version bất ngờ (`agent_info`).
  - **Alert theo burn rate của error budget** nhiều cửa sổ (ví dụ 5 phút và 1 giờ) thay vì ngưỡng cố định, để vừa bắt sự cố nhanh vừa ít báo động giả. Tôi đã thấy `AgentHighLatencyP95` chuyển `pending` ngay sau một lần khôi phục khi tải không đổi (nhiều khả năng do cửa sổ ít request lúc vừa khởi động lại, như đã nêu ở mục 4.2).
  - **Alert khi traffic biến mất hoặc giảm bất thường** (rule dạng "số request gần bằng 0"), vì các rule tỉ lệ lỗi hiện tại im lặng khi không có request nào.
  - **Chi phí:** alert theo ngân sách ngày thay vì chỉ theo tốc độ đốt tiền (ngưỡng 2 $/giờ hiện bị tải 100 user vượt qua), và theo dõi cost theo từng phiên bản agent.
  - **Saturation:** đo CPU/memory từng container (đang giới hạn 0,5 CPU và 256 MB) để biết khi nào thực sự cần scale.

### Gặp phải khi làm CP8

- **Docker Desktop tắt giữa chừng**: lệnh `docker pull` trong WSL báo `failed to connect to the docker API ... dockerDesktopLinuxEngine`. Mở lại Docker Desktop là chạy tiếp. Trước đó có một lần lỗi thoáng qua `error getting credentials` của credential helper.
- **Lỗi trong Dockerfile của stack Part 7** (code mẫu của đề): hai container `agent` crash liên tục với `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân là user `agent` có `HOME=/app` nên Python tìm package ở `/app/.local/...`, trong khi package được copy vào `/home/agent/.local/...`. Tôi xác nhận bằng cách chạy trong image (`site.getusersitepackages()` trả `/app/.local/...`, và đặt `PYTHONUSERBASE=/home/agent/.local` thì import được), rồi **thêm một dòng `ENV PYTHONUSERBASE=/home/agent/.local`** vào `06-lab-complete/benchmark-observability/production/Dockerfile` (Dockerfile của Part 5 đã có dòng này). Đây là thay đổi duy nhất của tôi trên code của stack production.
- **Jaeger 2.x** không có API `/api/services` và `/api/traces` cũ, nên tôi dùng `/api/v3/traces` (định dạng OTLP-JSON) để lấy trace ID cho báo cáo.
- **Số đo baseline đầu tiên bị lệch** (token/s, req/s thấp khoảng một nửa) vì chụp ngay sau khi agent vừa khởi động lại, khi cửa sổ `rate()` chưa đủ dữ liệu. Tôi phát hiện khi đối chiếu với số đo trước đó, rồi đo lại sau khi hệ thống ổn định và chỉ dùng bộ số đó trong báo cáo.
