# Proposal: Đánh giá và dự báo sản phẩm tiềm năng trên sàn thương mại điện tử

## 1. Bối cảnh và lý do chọn đề tài

Thương mại điện tử Việt Nam (Tiki, Shopee, Lazada...) sinh ra lượng dữ liệu sản phẩm rất lớn mỗi ngày: giá, số lượng đã bán, đánh giá, khuyến mãi... Người bán và nhà phân tích thị trường hiện chủ yếu quan sát các chỉ số này một cách thủ công, tại một thời điểm, nên khó nhận ra sản phẩm nào đang **tăng trưởng nhanh** (tiềm năng) so với sản phẩm đang đứng yên hoặc giảm.

Vấn đề đặt ra: nếu chỉ nhìn một lần quét dữ liệu (snapshot), không thể biết một sản phẩm có "tiềm năng" hay không — cần theo dõi **biến động qua nhiều ngày** (tốc độ tăng số lượng bán, tăng review, thay đổi giá) mới đánh giá được xu hướng. Đây là động lực để xây dựng một hệ thống thu thập dữ liệu định kỳ, lưu trữ lịch sử, và tính toán chỉ số tăng trưởng một cách tự động, có thể mở rộng.

## 2. Mục tiêu và câu hỏi nghiên cứu

**Mục tiêu tổng quát:** xây dựng một hệ thống end-to-end tự động thu thập, lưu trữ và phân tích dữ liệu sản phẩm trên sàn TMĐT (Tiki.vn) theo chu kỳ hàng ngày, từ đó phát hiện và xếp hạng những sản phẩm có dấu hiệu tăng trưởng tốt ("sản phẩm tiềm năng").

**Mục tiêu cụ thể:**
1. Thiết kế kiến trúc dữ liệu kiểu SDLF (Raw → Stage → Analytics) triển khai trên AWS, tự động hoá hoàn toàn bằng Infrastructure-as-Code (AWS CDK).
2. Xây dựng crawler thu thập dữ liệu sản phẩm theo nhiều ngành hàng, chạy tự động hàng ngày.
3. Xây dựng pipeline ETL (Glue + Apache Iceberg) làm sạch dữ liệu và tính các chỉ số tăng trưởng giữa các lần quét (growth rate).
4. Xây dựng mô hình ML để phân loại sản phẩm tiềm năng theo từng ngành hàng.
5. Trực quan hoá kết quả trên dashboard (QuickSight) phục vụ ra quyết định.

**Câu hỏi nghiên cứu chính:** làm sao để định nghĩa và đo lường "tiềm năng" của một sản phẩm một cách khách quan, có thể tính toán tự động ở quy mô lớn, mà không chỉ dựa vào giá trị tuyệt đối tại một thời điểm?

## 3. Vì sao đây là bài toán Big Data, và vì sao chọn kiến trúc SDLF trên AWS

| Đặc trưng 3V | Biểu hiện trong đề tài |
|---|---|
| Volume | Mỗi ngày crawl nhiều ngành hàng x nhiều trang sản phẩm; dữ liệu tích luỹ theo **lịch sử snapshot** (mỗi sản phẩm 1 dòng/ngày) nên tăng tuyến tính theo thời gian lưu trữ, không phải dữ liệu "trạng thái hiện tại" cố định kích thước |
| Velocity | Thu thập theo chu kỳ hàng ngày (có thể tăng tần suất), xử lý ETL tự động ngay sau khi crawl xong, không can thiệp thủ công |
| Variety | Dữ liệu bán cấu trúc (JSON từ API), nhiều ngành hàng với thuộc tính khác nhau, có trường thiếu/null cần chuẩn hoá (ví dụ `quantity_sold` fallback sang trường khác khi null) |

**Vì sao chọn kiến trúc SDLF (Serverless Data Lake Framework) trên AWS thay vì xử lý trong một script đơn lẻ:**
- Tách biệt rõ 3 tầng Raw / Stage / Analytics giúp dễ debug, truy vết lỗi, và cho phép tái xử lý một tầng mà không cần crawl lại.
- Serverless (Lambda, Glue, Step Functions) nghĩa là không cần quản lý server, chi phí tính theo lượt chạy thực tế — phù hợp quy mô đề tài (dữ liệu chỉ vài trăm-nghìn dòng/ngày).
- Apache Iceberg (table format) cho phép `MERGE INTO` idempotent (chạy lại không tạo dữ liệu trùng), schema evolution, và time-travel — cần thiết khi dữ liệu là lịch sử snapshot tích luỹ dài hạn.
- Toàn bộ hạ tầng được khai báo bằng AWS CDK (Infrastructure-as-Code), giúp triển khai/huỷ lại toàn bộ hệ thống lặp lại được, phục vụ tốt cho việc test và bảo vệ đề tài.

## 4. Kiến trúc hệ thống

```
EventBridge (cron 18:00 UTC)
        │
        ▼
Lambda: Crawler Tiki.vn  ──────────────────────────────────────┐
        │                                                       │
        ▼                                                       │
S3 Raw (JSON thô, partition theo dt=yyyy-mm-dd)                 │
        │                                                       │
        ▼                                                       │
┌─────────────────────────── Step Functions: product-pipeline ──┼───┐
│  Glue ETL: raw_to_stage                                        │   │
│     (làm sạch, khử trùng theo product_id + crawl_date)         │   │
│        │                                                       │   │
│        ▼                                                       │   │
│  S3 Stage — Apache Iceberg                                     │   │
│     (lịch sử snapshot: 1 dòng / sản phẩm / ngày)                │   │
│        │                                                       │   │
│        ▼                                                       │   │
│  Glue ETL: stage_to_analytics                                  │   │
│     (window function LAG() tính growth rate giữa 2 lần crawl)  │   │
└────────┼────────────────────────────────────────────────────────┘
         ▼
S3 Analytics — Apache Iceberg
   (sold_growth_rate, review_growth, potential_score)
         │
         ├──────────────────────────────┐
         ▼                              ▼
   Athena → QuickSight          ML (chạy local)
   (truy vấn SQL + dashboard)   train_potential_model.py
                                (phân loại is_potential
                                 theo từng ngành hàng)
```

Luồng liền (EventBridge → ... → QuickSight) chạy tự động hàng ngày, không cần can thiệp thủ công. Nhánh ML chạy riêng, cục bộ (local), khi đã tích lũy đủ dữ liệu lịch sử để huấn luyện mô hình — không nằm trong lịch tự động.

## 5. Nguồn dữ liệu và phương pháp thu thập

**Nguồn:** API nội bộ (không chính thức) của Tiki.vn (`api/personalish/v1/blocks/listings`), thu thập theo nhiều ngành hàng (category) cấu hình sẵn.

**Các thuộc tính thu thập:** tên sản phẩm, giá bán, giá gốc, % giảm giá, điểm đánh giá trung bình, số lượng review, số lượng đã bán, người bán và loại shop (chính hãng hay không).

**Cách thu thập:** một AWS Lambda chạy script crawler Python, được EventBridge kích hoạt theo lịch cố định mỗi ngày; kết quả được lưu dạng NDJSON lên S3 Raw, gộp theo ngày crawl (`dt=yyyy-mm-dd`).

**Xử lý dữ liệu thiếu/không đồng nhất:** một số trường có thể null (ví dụ `quantity_sold`) — crawler có các trường fallback (ví dụ dùng `amplitude.all_time_quantity_sold`) để giảm mất dữ liệu khi trường chính không có.

## 6. Phương pháp phân tích

**Định nghĩa "sản phẩm tiềm năng":** không dựa vào một ngưỡng tăng trưởng tuyệt đối chung cho toàn bộ hệ thống (vì các ngành hàng có quy mô doanh số rất khác nhau), mà xếp hạng **tương đối trong từng (ngành hàng, tháng)** — một sản phẩm được coi là tiềm năng nếu tốc độ tăng trưởng số lượng bán của nó nằm trong top phân vị cao nhất so với các sản phẩm cùng ngành hàng, cùng kỳ.

**Công thức tính growth metrics (tầng Analytics):** dùng window function `LAG(...) OVER (PARTITION BY product_id ORDER BY crawl_date)` để lấy giá trị snapshot ngay trước đó của cùng sản phẩm, từ đó tính:
- `sold_growth` = số lượng bán hiện tại − số lượng bán kỳ trước
- `sold_growth_rate` = `sold_growth` / số ngày giữa 2 lần crawl
- `review_growth` = số review hiện tại − số review kỳ trước
- `rating_change` = thay đổi điểm đánh giá trung bình
- `potential_score` = 0.7 × `sold_growth_rate` + 0.3 × `review_growth` (chỉ số heuristic dùng cho dashboard, không phải kết quả của mô hình ML)

**Mô hình học máy (`ml/train_potential_model.py`):** dùng Random Forest, gán nhãn `is_potential = 1` cho sản phẩm có `sold_growth_rate` thuộc top phân vị trong nhóm (ngành hàng, tháng) của nó. Đặc trưng đầu vào gồm giá, tỷ lệ giảm giá, điểm đánh giá, loại shop (chính hãng hay không), và các chỉ số tăng trưởng ở trên.

## 7. Công nghệ sử dụng

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Thu thập dữ liệu | AWS Lambda (Python) | Crawl API Tiki.vn, không cần quản lý server |
| Kích hoạt tự động | Amazon EventBridge | Lập lịch chạy crawler hàng ngày (cron) |
| Lưu trữ | Amazon S3 (5 bucket: raw/stage/analytics/scripts/athena-results) | Data lake, lưu dữ liệu theo từng tầng |
| Xử lý ETL | AWS Glue (PySpark, Glue 4.0) | Làm sạch dữ liệu, tính chỉ số tăng trưởng |
| Định dạng bảng | Apache Iceberg | ACID, upsert idempotent, schema evolution, time-travel |
| Điều phối pipeline | AWS Step Functions | Chạy nối tiếp 2 Glue Job, xử lý lỗi |
| Truy vấn | Amazon Athena | SQL trên dữ liệu Iceberg |
| Trực quan hoá | Amazon QuickSight | Dashboard cho người dùng cuối |
| Hạ tầng | AWS CDK (Python) | Infrastructure-as-Code, triển khai/huỷ lặp lại được |
| Học máy | scikit-learn (Random Forest) | Phân loại sản phẩm tiềm năng, chạy cục bộ |

## 8. Kế hoạch thực hiện

| Giai đoạn | Nội dung | Thời gian dự kiến |
|---|---|---|
| 1 | Thiết kế kiến trúc, viết crawler, kiểm thử thu thập dữ liệu thủ công | Tuần 1-2 |
| 2 | Xây dựng hạ tầng AWS bằng CDK (S3, Glue, IAM), triển khai thử | Tuần 3-4 |
| 3 | Viết Glue job raw_to_stage và stage_to_analytics, kiểm thử pipeline | Tuần 5-6 |
| 4 | Tích hợp Step Functions + EventBridge, chạy tự động nhiều ngày để có dữ liệu lịch sử | Tuần 7-8 |
| 5 | Xây dựng và huấn luyện mô hình ML phân loại sản phẩm tiềm năng | Tuần 9-10 |
| 6 | Xây dựng dashboard QuickSight, tổng hợp báo cáo, chuẩn bị bảo vệ | Tuần 11-12 |

## 9. Kết quả kỳ vọng

- Một hệ thống thu thập dữ liệu Tiki.vn tự động, chạy ổn định hàng ngày không cần can thiệp thủ công.
- Pipeline ETL tự động tính toán chỉ số tăng trưởng sản phẩm theo thời gian, lưu trữ dưới dạng Iceberg table có thể truy vấn qua Athena.
- Một mô hình ML phân loại sản phẩm tiềm năng theo ngành hàng, có thể đánh giá bằng precision/recall trên dữ liệu thực tế đã thu thập.
- Dashboard trực quan (QuickSight) cho phép xem danh sách sản phẩm tiềm năng, xu hướng tăng trưởng theo ngành hàng.
- Toàn bộ hạ tầng có thể triển khai lại từ đầu bằng vài lệnh CDK (phục vụ demo/bảo vệ đề tài).

## 10. Hạn chế hiện tại và hướng phát triển

**Hạn chế:**
- Dữ liệu mới có từ một nguồn (Tiki.vn); chưa mở rộng sang Shopee/Lazada để so sánh đa sàn.
- `potential_score` và các chỉ số tăng trưởng đọc ra giá trị `0` (không phải "chưa xác định") ở lần crawl đầu tiên của một sản phẩm, do chưa có snapshot trước đó để so sánh — cần ít nhất 2 ngày dữ liệu mới có ý nghĩa.
- Mô hình ML hiện chạy cục bộ (không tự động hoá trên cloud), cần chạy lại thủ công khi muốn huấn luyện lại trên dữ liệu mới.

**Hướng phát triển:**
- Mở rộng crawler sang các sàn TMĐT khác để so sánh sản phẩm tiềm năng đa sàn.
- Tự động hoá việc huấn luyện lại mô hình ML theo chu kỳ (ví dụ qua AWS Glue/SageMaker).
- Phân biệt rõ sản phẩm "chưa đủ dữ liệu" và "không tăng trưởng" trong các chỉ số growth, thay vì gộp chung thành `0`.
- Thêm cảnh báo tự động (ví dụ qua SNS) khi phát hiện sản phẩm tăng trưởng vượt ngưỡng.
