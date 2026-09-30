# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (99.5% request thành công và `latency_ms <= 3000` trong 28 ngày); SLI là `response_sent.latency_ms`.
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 2000ms` liên tục 5 phút. Ngưỡng 2000ms thấp hơn SLO 3000ms để cảnh báo trước khi tiêu error budget.
- Ảnh hưởng tới người dùng: người dùng chờ lâu hơn trước khi nhận câu trả lời; nếu kéo dài sẽ vượt SLO và request bị tính vào error budget.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Latency percentiles and TTFT**: xác nhận P95/P99 tăng từ phút nào; so với TTFT P95 — TTFT bình thường mà latency tăng nghĩa là phần chậm nằm ngoài lúc LLM bắt đầu trả token (thường là retrieval).
  2. Lọc log trong khoảng đó: `event == "response_sent" and latency_ms > 2000`, lấy một `correlation_id`.
  3. Mở trace trên Langfuse có metadata `correlation_id` đó, so sánh thời lượng span `retrieval` và `llm-generation` để khoanh vùng bước chậm.
- Mitigation tạm thời: nếu `retrieval` chậm — kiểm tra/khôi phục vector store, bật cache hoặc giảm top-k; nếu `llm-generation` chậm sau khi đổi prompt — rollback label `production` về version trước; khi demo, tắt practice scenario (`inject_incident.py --scenario rag_slow --disable`).
- Owner: `student-2A202602547`

## Alert 2

- Tên: `HighErrorRateOrRetrievalFailure`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` và guardrail `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90`.
- Điều kiện và thời gian duy trì: `error_rate_pct > 2%` **hoặc** retrieval success `< 90%` liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500, không có câu trả lời; mỗi request lỗi tiêu thẳng vào error budget.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Error rate and retrieval success**: xem error rate, breakdown theo `error_type` và retrieval success rate từ phút nào.
  2. Lọc log `event == "request_failed"`, xem `error_type`, `tool_name`, `tool_success` và `payload.detail`; lấy một `correlation_id`.
  3. Mở trace cùng `correlation_id`: span nào có level `ERROR` (ví dụ `retrieval` với `RuntimeError`) và span nào không chạy tới.
- Mitigation tạm thời: nếu lỗi ở retrieval — chuyển sang fallback answer không dùng context hoặc khôi phục kết nối vector store; nếu lỗi bắt đầu ngay sau khi deploy/đổi prompt — rollback; tắt practice scenario `tool_fail` khi demo.
- Owner: `student-2A202602547`

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: `warning`
- Duration: `15m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail chi phí `daily_cost_usd_max: 2.5`; SLI là `response_sent.cost_usd` và `tokens_out`.
- Điều kiện và thời gian duy trì: `avg(response_sent.cost_usd) > 0.004 USD/request` (gấp đôi baseline ~0.002) liên tục 15 phút.
- Ảnh hưởng tới người dùng: không làm hỏng câu trả lời ngay, nhưng làm cạn ngân sách ngày và thường đi kèm câu trả lời dài/lan man hơn; nếu không xử lý có thể phải chặn traffic.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Cost over time** và **Input and output tokens**: cost tăng do `tokens_in` (prompt/context dài) hay `tokens_out` (câu trả lời dài).
  2. Lọc log `event == "response_sent"` có `cost_usd` cao nhất, lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: xem `usage` và `cost` của span `llm-generation`, cùng `prompt_version` để biết có trùng lúc đổi prompt không.
- Mitigation tạm thời: rollback prompt nếu version mới làm câu trả lời dài hơn; đặt `max_tokens` cho output; chuyển feature ít quan trọng sang model rẻ hơn; tắt practice scenario `cost_spike` khi demo.
- Owner: `student-2A202602547`
