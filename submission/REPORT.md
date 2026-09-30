# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Luu Nguyen Khoi
- **MSSV:** 2A202602547
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/w1n10/K4-L3B-Day13-LuuNguyenKhoi-2A202602547-Monitoring-LLMOps
- **Commit SHA cuối:** `2fc1651593ebf1889ab9a43c01be0e54cd06de2b`
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, incident `rag_slow`, seed 1312)
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602547`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | [`evidence/01-pytest.txt`](evidence/01-pytest.txt) |
| Log validator | [`evidence/02-log-validator.txt`](evidence/02-log-validator.txt) (baseline: [`evidence/baseline/`](evidence/baseline/)) |
| Dashboard validator | [`evidence/03-dashboard-validator.txt`](evidence/03-dashboard-validator.txt) |
| Structured log | [`evidence/04-structured-log.txt`](evidence/04-structured-log.txt) |
| PII redaction | [`evidence/05-pii-redaction.txt`](evidence/05-pii-redaction.txt) |
| Trace list | [`evidence/06-trace-list.png`](evidence/06-trace-list.png) |
| Trace waterfall | [`evidence/07-trace-waterfall.png`](evidence/07-trace-waterfall.png) |
| Trace metadata | [`evidence/08-trace-metadata.png`](evidence/08-trace-metadata.png) |
| Prompt versions | [`evidence/09-prompt-versions.png`](evidence/09-prompt-versions.png) |
| Prompt rollback | [`evidence/10-prompt-rollback.png`](evidence/10-prompt-rollback.png) |
| Dashboard runtime | [`evidence/11-dashboard-overview.png`](evidence/11-dashboard-overview.png) |
| Incident metric | [`evidence/12-incident-metric.png`](evidence/12-incident-metric.png) |
| Incident log | [`evidence/13-incident-log.png`](evidence/13-incident-log.png) |
| Incident trace | [`evidence/14-incident-trace.png`](evidence/14-incident-trace.png) |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (thiếu correlation ID + enrichment) | 100/100 | Chạy trên log sau CP3: 125 record, 60 correlation ID, 0 thiếu field, 0 PII leak (evidence `02`) |
| `validate_dashboard.py` | 6/6 | 6/6 | Contract giữ nguyên; thêm dashboard runtime `scripts/build_dashboard.py` |
| `pytest` | 22 passed | 29 passed | Thêm test PII, correlation/no-leak, scrub-before-write, child observations, dashboard |
| Số traces hợp lệ | 0 (chưa có key Langfuse) | 45 | Trace `lab-agent-run` do tôi tạo trong project cá nhân (đếm qua API observations, 3 giờ gần nhất, gồm trace baseline/candidate/incident); mỗi trace có `correlation_id` khớp log |
| Số PII leak | 0 | 0 | Baseline 0 vì preview đã qua `summarize_text`; nay scrub ở tầng logging cho mọi field |
| Latency P95 / TTFT P95 | 153 ms / 50 ms | 2,653 ms / 50 ms (lần chạy practice có `rag_slow`, ảnh `11`); challenge: 2,863–2,905 ms (5 request, mục 7) | Server-side `latency_ms`; TTFT không đổi khi retrieval chậm |
| Retrieval success rate | 100% | 82% (lần chạy practice có `tool_fail`, ảnh `11`) | 20 `RuntimeError` từ practice scenario; challenge `rag_slow` giữ `tool_success=true` |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `app/middleware.py` gọi `clear_contextvars()` đầu mỗi request, nhận `x-request-id` nếu chỉ gồm `[A-Za-z0-9._-]` (≤64 ký tự, chống log injection), nếu không thì sinh `req-<8-hex>`; bind vào structlog contextvars, lưu ở `request.state`, truyền vào agent/trace metadata và trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, `user_id_hash` (SHA-256 cắt 12 ký tự, không log user_id thô), `session_id`, `feature`, `model`, `env`; `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` đứng sau `format_exc_info` và trước `JsonlFileProcessor`/`JSONRenderer`, scrub đệ quy mọi field (trừ field hệ thống `ts`, `level`, `correlation_id`, `user_id_hash`). `app/pii.py` có pattern email, thẻ thanh toán, CCCD 12 số, điện thoại VN (0/+84, có phân tách), hộ chiếu; pattern dài chạy trước pattern ngắn.
- **Cách kiểm chứng kết quả:** `tests/test_pii.py`, `tests/test_correlation_logging.py` (gửi request chứa PII qua ASGI và đọc file log thật); `validate_logs.py` quét độc lập: 0 leak. Evidence `04`, `05`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key trong `.env` thuộc project `day13-k4-l3b-2A202602547`; mọi trace đều sinh từ `load_test.py` chạy trên máy tôi và mang metadata `correlation_id` (dạng `req-xxxxxxxx`) trùng với dòng trong `data/logs.jsonl` cục bộ, ví dụ `req-3568e7a0` ↔ trace `2f6e645aa0f1e1b1c689b58b71a918a8`. Ảnh `06`, `07`, `08`.
- **Cấu trúc root/retrieval/generation observations:** trace `day13-agent-request` → root `lab-agent-run` (agent) → `retrieval` (retriever, input là query preview đã scrub, output `doc_count`, đánh dấu `ERROR` nếu lỗi) và `llm-generation` (generation: model, prompt link, `usage_details` input/output, `cost_details` input/output/total, `completion_start_time` = start + TTFT). Helper `start_observation` trong `app/tracing.py`.
- **Cách nối trace với log:** `propagate_attributes(metadata={"correlation_id": ...})` gắn cùng `correlation_id` lên mọi observation của trace; lọc trace trên Langfuse theo metadata này.
- **Prompt name:** `day13-chat`
- **Version/label baseline:** `day13-chat` v1, commit message `v1 baseline`, tạo 9/30/2026 11:07:43; mang label `baseline`, và `production` khi ở trạng thái gốc/sau rollback (ảnh `10`).
- **Version/label candidate:** `day13-chat` v2, thêm dòng `Answer concisely in at most 3 sentences.`, tạo 11:09:24; mang label `candidate` + `latest`, và `production` khi được promote (ảnh `09`).
- **Trace ID của mỗi version:** chạy cùng input `What is your refund policy?` (feature `qa`) với `LANGFUSE_PROMPT_LABEL` đặt bằng biến môi trường. `baseline` → prompt v1: trace `d11973404b96f1be89a0d0b4f62b5f31` (`correlation_id=req-d264b0a6`, `prompt_label=baseline`, `prompt_version=1`, `prompt_source=langfuse`). `candidate` → prompt v2: trace `d800b86a938c75a0a42fc90d6148c58b` (`correlation_id=req-f37eb67f`, `prompt_label=candidate`, `prompt_version=2`, `prompt_source=langfuse`). Sau rollback, request với label `production` cũng lấy v1, ví dụ trace `8d95e54ffb4b08d9a36abcd73aafede9` (`req-e2222b1e`, `prompt_version=1`). Các trace incident ở mục 7 tạo trước khi có prompt nên ghi `local-fallback`.
- **Cách promote và rollback `production`:** trên Langfuse UI, chuyển label `production` giữa hai version. Ảnh `09`: `production` ở v2 (promote). Ảnh `10`: `production` ở v1 cùng `baseline`, v2 chỉ còn `latest` + `candidate` (rollback). App không sửa code, chỉ đọc theo `LANGFUSE_PROMPT_NAME=day13-chat` và `LANGFUSE_PROMPT_LABEL=production`; các request sau rollback lấy `prompt_version=1` (ví dụ trace `8d95e54ffb4b08d9a36abcd73aafede9`, `req-e2222b1e`).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `python scripts/build_dashboard.py [--watch]` đọc `data/logs.jsonl`, lấy title/unit/threshold từ `config/dashboard.yaml`, tạo `data/dashboard.html` (time range 60 phút, refresh 30s, threshold line, trạng thái đạt/vi phạm, bảng dữ liệu). Ảnh `11` chụp từ lần chạy practice (log lưu ở `data/logs.baseline.jsonl`, không commit) qua workload baseline → `rag_slow` → `tool_fail` → `cost_spike` → hồi phục: panel errors báo vi phạm (18% error, retrieval 82%), latency P95 lên 2,653 ms ở phút `rag_slow`, cost tăng ở phút `cost_spike`.
- **SLO và lý do chọn:** `config/slo.yaml` — 99.5% request thành công và `latency_ms ≤ 3000` trong 28 ngày. Baseline P95 153 ms, nên 3000 ms chỉ bị vi phạm khi có sự cố thật; 99.5% vì phụ thuộc LLM/vector store bên ngoài.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% tổng request. 10,000 request/28 ngày → tối đa 50 request lỗi hoặc chậm hơn 3000 ms. Tiêu >50% budget trong 7 ngày thì dừng promote prompt/model mới.
- **Ba alert và runbook tương ứng:** `config/alert_rules.yaml` + `docs/alerts.md`: `HighLatencyP95` (warning, P95 > 2000 ms trong 5m — sớm hơn SLO 3000 ms), `HighErrorRateOrRetrievalFailure` (critical, error > 2% hoặc retrieval < 90% trong 5m), `CostPerRequestSpike` (warning, avg cost > 0.004 USD, gấp đôi baseline, trong 15m). Tất cả gửi Slack `#k4-l3b-alerts`, owner `student-2A202602547`. Lưu ý: với `rag_slow`, P95 = 2,653 ms chưa vượt SLO 3000 ms nhưng đã kích hoạt alert 2000 ms — đúng mục đích cảnh báo sớm.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (`incident: rag_slow`, `affected_feature: monitoring`, ngưỡng 2000 ms)
- **Khoảng thời gian điều tra:** 10:40:02 – 10:40:17 giờ VN (03:40:02Z – 03:40:17Z) ngày 2026-09-30, từ lúc bật `rag_slow` bằng `inject_incident.py` đến khi 5 request challenge xong
- **Triệu chứng từ metrics:** panel Latency (ảnh `12`) tăng vọt trong khoảng trên. Cả 5 request `feature=monitoring` có `latency_ms` phía server 2863–2905 ms, vượt ngưỡng 2000 ms; traffic bình thường 366–450 ms (chậm khoảng 7 lần). TTFT không đổi (50 ms). `tool_success=true` cho cả 5 request nên error rate không tăng — đây là sự cố chậm, không phải lỗi. Client đo 8.7–14.4 s vì 5 request bị xếp hàng nối tiếp; số liệu dùng làm bằng chứng là `latency_ms` trong log.
- **Log line và correlation ID liên quan:** `correlation_id=req-3568e7a0`, event `response_sent`, `feature=monitoring`, `latency_ms=2905`, `ttft_ms=50`, `tool_name=retrieval`, `tool_success=true`, `session_id=k4-l3b-challenge-s03` (ảnh `13`). Bốn request còn lại: `req-07a4567a` (2870 ms), `req-47d192b3` (2890 ms), `req-62832781` (2863 ms), `req-60fd19f8` (2865 ms).
- **Trace ID và span gây ảnh hưởng:** trace `2f6e645aa0f1e1b1c689b58b71a918a8` (metadata `correlation_id=req-3568e7a0`, tổng 2.91 s). Span `retrieval` mất 2.50 s, còn `llm-generation` chỉ 0.15 s (ảnh `14`; cùng cấu trúc ở ảnh `07`). Span retrieval chiếm khoảng 86% thời gian request.
- **Root cause:** bước retrieval bị chậm thêm 2.5 giây do incident `rag_slow` (trong `app/mock_rag.py`, khi `rag_slow` bật thì gọi `time.sleep(2.5)`). Metric (P95 latency tăng), log (`latency_ms` ≈ 2.9 s, `tool_name=retrieval`) và trace (span `retrieval` 2.50 s) cùng chỉ về retrieval; LLM generation và TTFT không đổi.
- **Fix action:** tắt incident bằng `python scripts/inject_incident.py --disable` (kết quả `rag_slow: False`); trong sự cố thật thì kiểm tra vector store/nguồn retrieval, khôi phục hoặc chuyển sang cache/fallback.
- **Preventive measure:** giữ alert `HighLatencyP95` (P95 > 2000 ms trong 5 phút) kèm runbook trong `docs/alerts.md`; thêm timeout và cache cho retrieval; theo dõi thời gian theo từng span để khoanh vùng nhanh; dùng `correlation_id` làm khóa nối log và trace.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt processor `scrub_event` trước bộ ghi file/JSON renderer và scrub đệ quy mọi field, để PII bị che trước khi ghi xuống `data/logs.jsonl` thay vì che sau. Middleware chỉ nhận `x-request-id` từ client nếu khớp `[A-Za-z0-9._-]{1,64}` để tránh log injection.
- **Một lỗi/blocker đã gặp:** load test báo `[404] None` và validator báo `data\logs.jsonl not found`; sau đó là `WinError 10061` khi đổi cổng.
- **Cách tìm nguyên nhân và xử lý:** kiểm tra `/health` thì thấy không phải app lab, tiến trình trên cổng 8000 là container Docker của project khác. Chạy app lab ở cổng khác và đặt `LAB_BASE_URL` (README hướng dẫn `--port 8013`); khi cổng 8000 trống thì chạy lại ở 8000. `WinError 10061` là do script gọi cổng không có server nào lắng nghe.
- **Cách hiểu luồng Metrics → Logs → Traces:** metric (dashboard) cho biết có bất thường và khi nào; log lọc trong khoảng đó để lấy `correlation_id` của một request chậm; trace cùng `correlation_id` cho thấy span nào chiếm thời gian. Cả ba phải chỉ về một nguyên nhân thì kết luận mới hợp lệ — ở đây là retrieval 2.5 s.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt version cho phép biết một request dùng prompt nào và đổi/rollback bằng label mà không sửa code; token/cost phát hiện prompt dài hoặc chi phí tăng; SLO 99.5% với error budget 0.5% cho biết khi nào nên dừng promote prompt/model mới.
- **Điều quan trọng nhất đã học:** khoanh vùng sự cố bằng dữ liệu từ ba nguồn cùng khớp một request, không suy đoán từ một nguồn.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** (1) chưa có trace chụp lúc `production` đang trỏ v2 (promote) — chỉ có trace baseline/candidate theo label và trace sau rollback về v1; (2) 23 trace đầu (kể cả trace incident) tạo trước khi có prompt nên ghi `local-fallback`; (3) 3 request đầu của lần chạy baseline concurrency 5 chậm 5–11 s (`req-f67b19bf`, `req-0a60f9d6`), chưa xác định nguyên nhân; (4) evidence `04`, `05` và ảnh `11` lấy từ lần chạy practice trước khi đổi tên log thành `logs.baseline.jsonl`; evidence `01`–`03` chạy lại sau CP3 trên `data/logs.jsonl` hiện tại; (5) chưa chạy lại toàn bộ test/validator trên commit cuối (làm ở CP4).

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
