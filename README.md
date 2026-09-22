# Đánh giá & Dự báo Sản phẩm Tiềm năng (Thương mại điện tử) — Pipeline Big Data

Đồ án môn Big Data. Xây dựng một phiên bản **SDLF (Serverless Data Lake
Framework)** đơn giản hóa, tự dựng trên AWS để: crawl định kỳ dữ liệu sản
phẩm trên sàn TMĐT (Tiki), theo dõi sự thay đổi theo thời gian (lượt bán,
review, rating), từ đó **đánh giá và dự báo sản phẩm nào đang có tiềm năng
tăng trưởng**.

## 1. Mô tả đề bài (Project description)

- **Tên đề tài**: Đánh giá và dự báo sản phẩm tiềm năng trên sàn thương mại
  điện tử
- **Nguồn dữ liệu**: crawl từ API listing (không chính thức) của
  `tiki.vn`, có thể mở rộng thêm `shopee.vn`/`lazada.vn` để tăng tính đa
  dạng schema. Các trường chính: mã sản phẩm, tên, ngành hàng, giá, giá gốc,
  rating trung bình, số lượng review, số lượng đã bán, người bán.
- **Yêu cầu / chức năng**:
  - Crawl định kỳ (hàng ngày) → mỗi sản phẩm có nhiều **snapshot** theo thời
    gian, không chỉ một điểm dữ liệu tĩnh
  - Nhiều nguồn/ngành hàng với schema không hoàn toàn giống nhau
  - Dữ liệu tích lũy dần, càng crawl lâu càng có nhiều lịch sử để so sánh
  - Làm sạch/chuẩn hóa dữ liệu thô, sau đó **tính tốc độ tăng trưởng**
    (lượt bán, review, rating) giữa các snapshot liên tiếp của cùng một sản
    phẩm — đây là tín hiệu cốt lõi để xác định "tiềm năng"
  - Phân tích SQL: xếp hạng sản phẩm tăng trưởng nhanh theo ngành hàng, xu
    hướng tăng trưởng theo thời gian, tương quan giữa giảm giá và tăng
    trưởng
  - Mô hình ML phân loại/dự báo sản phẩm nào sẽ vào nhóm "tiềm năng" ở kỳ
    tiếp theo
  - Dashboard QuickSight dựng trên Athena

## 2. Vì sao chọn kiến trúc này? (Big Data 3V)

- **Volume**: hàng nghìn sản phẩm × tích lũy một snapshot mỗi ngày → dữ
  liệu phình to đều đặn theo thời gian (khác với dữ liệu tĩnh chỉ crawl một
  lần).
- **Velocity**: crawler chạy theo lịch (EventBridge cron hàng ngày). Đặc
  biệt với bài toán này, velocity không chỉ để "có thêm dữ liệu" mà còn là
  **điều kiện bắt buộc** — "tiềm năng" là một khái niệm về *tốc độ thay
  đổi*, không thể tính được nếu chỉ có một lần crawl duy nhất.
- **Variety**: các sàn TMĐT khác nhau (Tiki/Shopee/Lazada) có cấu trúc API/
  trường dữ liệu khác nhau → cần bước "clean & standardize" để gộp về một
  schema chung.

## 3. Sơ đồ kiến trúc

```
EventBridge (lịch chạy cron hàng ngày)
      │
      ▼
Crawler (Lambda gọi API Tiki)              ← lấy snapshot sản phẩm mỗi ngày
      │  ghi JSON thô theo từng nguồn/ngày
      ▼
S3 Raw (landing zone)                     ← vùng lưu dữ liệu thô, bất biến
      │
      ▼  Glue Job: raw_to_stage.py (làm sạch, ép kiểu, khử trùng lặp trong ngày)
S3 Stage ── bảng Iceberg: lịch sử snapshot theo (product_id, crawl_date) ──┐
      │                                                                    │  Glue Data Catalog
      ▼  Glue Job: stage_to_analytics.py (so sánh snapshot liên tiếp → tính growth)
S3 Analytics ── bảng Iceberg: sold_growth_rate, review_growth, potential_score ┘
      │
      ├──► Athena (truy vấn SQL) ──► QuickSight (dashboard xếp hạng tiềm năng)
      └──► Glue Python shell / SageMaker (mô hình phân loại sản phẩm tiềm năng)

Step Functions điều phối toàn bộ: crawl → raw_to_stage → stage_to_analytics
```

### Vì sao dùng Apache Iceberg (thay vì Parquet thường)?

Đây là phần "đào sâu công nghệ" (technology deep-dive) của đồ án:

- **Schema evolution**: API của sàn TMĐT thay đổi trường dữ liệu theo thời
  gian → Iceberg cho phép thêm/đổi cột mà không phải ghi lại toàn bộ lịch
  sử snapshot đã crawl.
- **ACID / upsert (MERGE INTO)**: khóa hợp lệ ở đây là `(product_id,
  crawl_date)` — nếu một lần crawl bị chạy lại trong cùng ngày, MERGE đảm
  bảo không tạo dòng trùng.
- **Time travel**: truy vấn bảng tại một snapshot quá khứ để tái lập bảng
  xếp hạng "sản phẩm tiềm năng" của tuần trước, hoặc so sánh trước/sau khi
  đổi công thức tính `potential_score`.
- **Partition pruning**: Athena chỉ quét đúng phân vùng `year_month` cần
  thiết thay vì toàn bộ lịch sử snapshot.

Xem chi tiết mô hình dữ liệu, công thức tính growth, và state machine Step
Functions tại [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 4. Cấu trúc thư mục — mỗi phần là gì, tại sao có

```
crawler/            Thu thập snapshot sản phẩm hàng ngày từ Tiki → JSON
glue_jobs/           Các job PySpark trên AWS Glue: raw → stage → analytics
infra/               Hạ tầng AWS dưới dạng code (CDK Python)
ml/                  Huấn luyện mô hình phân loại sản phẩm tiềm năng
dashboard/           Ghi chú cấu hình dashboard QuickSight (làm trên console)
docs/                Tài liệu kiến trúc chi tiết
```

### `crawler/` — tại sao có, dùng để làm gì

Là **nguồn sinh dữ liệu** — mỗi lần chạy tạo ra một "lát cắt thời gian"
(snapshot) của tập sản phẩm đang theo dõi.

| File | Vai trò |
|---|---|
| `config.py` | Cấu hình dùng chung: header HTTP, độ trễ giữa các request (crawl lịch sự), danh sách `TIKI_CATEGORIES` (mã ngành hàng cần theo dõi — lấy từ URL trang danh mục trên tiki.vn), đường dẫn ghi S3. |
| `utils.py` | Hàm tiện ích: `safe_get` để đọc an toàn các trường JSON lồng nhau (API Tiki không phải lúc nào cũng trả đủ trường), và hai hàm ghi kết quả ra local hoặc S3. |
| `tiki_crawler.py` | Script crawl chính — gọi thẳng API listing JSON của Tiki (không cần BeautifulSoup vì dữ liệu đã có cấu trúc), lặp qua từng ngành hàng trong `TIKI_CATEGORIES`, bóc các trường: `product_id`, `price`, `original_price`, `rating_average`, `review_count`, `quantity_sold`. **Lưu ý quan trọng**: đây là API không chính thức, cấu trúc response có thể đổi bất cứ lúc nào — cần kiểm tra lại qua tab Network của trình duyệt trước khi coi là ổn định. |
| `lambda_handler.py` | Điểm vào khi chạy crawler dưới dạng AWS Lambda, được EventBridge gọi theo lịch mỗi ngày. |

Dữ liệu ra là **JSON thô theo từng dòng (NDJSON)**, ghi vào
`raw/source=tiki/dt=<ngày>/` — giữ nguyên bản thô để có thể xử lý lại nếu
sau này phát hiện logic clean/transform bị sai.

### `glue_jobs/clean_transform/` — tại sao tách 2 job, và vì sao Stage là "lịch sử" chứ không phải "trạng thái hiện tại"

Đây là phần xử lý cốt lõi. Điểm khác biệt quan trọng so với một pipeline
"làm sạch rồi lưu" thông thường: **một snapshot đơn lẻ không nói lên được
gì về "tiềm năng"** — phải so sánh với snapshot trước đó của cùng sản phẩm
mới tính được tốc độ tăng trưởng. Vì vậy:

| File | Vai trò |
|---|---|
| `raw_to_stage.py` | Đọc JSON thô → ép kiểu, loại dòng thiếu giá, coi `quantity_sold`/`review_count` bị thiếu là 0 (vì sản phẩm mới có baseline = 0 vẫn là tín hiệu hữu ích, không nên bỏ), khử trùng lặp **trong cùng một ngày** (khóa `product_id + crawl_date`, không khử theo `product_id` một mình). Kết quả là bảng Stage lưu **toàn bộ lịch sử snapshot**, mỗi sản phẩm có nhiều dòng theo từng ngày crawl. |
| `stage_to_analytics.py` | Dùng window function (`LAG(...) OVER (PARTITION BY product_id ORDER BY crawl_date)`) để lấy snapshot liền trước của từng sản phẩm, từ đó tính: `sold_growth_rate` (tốc độ tăng lượt bán/ngày), `review_growth`, `rating_change`, `discount_pct`, và một `potential_score` gộp (chỉ dùng để xếp hạng nhanh trên dashboard, **không phải** kết quả của mô hình ML). Ghi vào bảng Iceberg tầng Analytics, partition theo `year_month`. |

### `infra/` — tại sao dùng CDK thay vì bấm tay trên console

Dùng **Infrastructure as Code (IaC)** để tái tạo lại toàn bộ hạ tầng nhất
quán khi demo/nộp bài, dễ review qua code, và dễ `cdk destroy` để tránh phát
sinh chi phí AWS khi không dùng nữa.

| File | Vai trò |
|---|---|
| `app.py` | Điểm vào CDK — ghép 3 stack theo đúng thứ tự phụ thuộc (storage → glue → pipeline). |
| `infra/storage_stack.py` | Tạo 5 bucket S3: `raw`, `stage`, `analytics`, `scripts` (chứa code PySpark), `athena-results`. Dùng `RemovalPolicy.RETAIN` vì đây là data lake — không muốn `cdk destroy` xóa mất lịch sử snapshot đã crawl được nhiều ngày. |
| `infra/glue_stack.py` | Tạo 2 database Glue Data Catalog (`product_stage`, `product_analytics`), IAM role cho Glue job, tự động upload script từ `glue_jobs/` lên bucket scripts, và định nghĩa 2 Glue Job (`raw-to-stage`, `stage-to-analytics`) với cấu hình Iceberg. |
| `infra/pipeline_stack.py` | Tạo Lambda chạy `tiki_crawler` qua `lambda_handler.py`, gắn lịch EventBridge (mặc định 18:00 UTC hàng ngày), và định nghĩa Step Functions state machine `product-pipeline` nối tiếp 2 Glue job. |

### `ml/` — tại sao là bài toán phân loại, không phải hồi quy giá

`train_potential_model.py` định nghĩa nhãn `is_potential` là **top quantile
của `sold_growth_rate` trong cùng ngành hàng và cùng tháng** (mặc định
top 20%) — dùng ngưỡng tương đối theo từng nhóm thay vì một ngưỡng tuyệt
đối chung, vì mức tăng trưởng "nhanh" của điện thoại và của thời trang có
baseline hoàn toàn khác nhau. Đặc trưng đầu vào (`price`, `discount_pct`,
`rating_average`, `review_count`, `review_growth`, `category`, `source`)
đều là thông tin **quan sát được trước khi biết kết quả kỳ tới**, để mô
hình dùng được cho việc dự báo thật, không chỉ giải thích quá khứ. Mô hình
`RandomForestClassifier` báo cáo ROC-AUC và classification report; có thể
đưa nguyên logic này vào SageMaker Training Job khi cần chạy tự động.

### `dashboard/` — tại sao không có code

QuickSight không có CDK support đầy đủ để định nghĩa dashboard bằng code,
nên phần này cấu hình tay trên console. File `dashboard/README.md` liệt kê
các biểu đồ cần dựng (bảng xếp hạng sản phẩm tiềm năng, xu hướng tăng
trưởng theo ngành hàng, tương quan giảm giá–tăng trưởng, so sánh dự báo mô
hình với kết quả thực tế) để không bị thiếu ý so với yêu cầu đề bài khi làm
trên console.

### `docs/ARCHITECTURE.md` — tại sao tách riêng khỏi README

README tập trung vào "làm sao để chạy được"; `docs/ARCHITECTURE.md` đi sâu
vào "tại sao thiết kế schema/partition như vậy" — đặc biệt là lý do bảng
Stage phải là lịch sử snapshot thay vì trạng thái hiện tại, công thức tính
growth, và cách tính storage volume estimate khi dữ liệu tăng tuyến tính
theo số ngày retention (khác với dữ liệu "trạng thái hiện tại" thông
thường).

## 5. Hướng dẫn cài đặt & chạy

### Bước 0. Yêu cầu môi trường
- Python 3.11+, Node.js 18+ (CLI của CDK), AWS CLI đã cấu hình
  account/profile
- Docker (CDK cần Docker để đóng gói dependency cho Lambda crawler)
- `npm install -g aws-cdk`

### Bước 1. Triển khai hạ tầng (S3, Glue, Step Functions)
```bash
cd infra
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cdk bootstrap                # chỉ cần chạy 1 lần cho mỗi account/region
cdk deploy --all
```
Lệnh này tạo ra:
- Bucket S3: `<prefix>-raw`, `<prefix>-stage`, `<prefix>-analytics`,
  `<prefix>-scripts`, `<prefix>-athena-results`
- Database Glue Data Catalog: `product_stage`, `product_analytics`
- Glue Job: `raw-to-stage`, `stage-to-analytics` (PySpark, hỗ trợ Iceberg)
- Step Functions state machine: `product-pipeline`
- IAM role giới hạn đúng phạm vi cần thiết

> **Lưu ý**: đổi `PREFIX` trong `infra/app.py` thành giá trị duy nhất của
> riêng bạn trước khi deploy, vì tên bucket S3 phải duy nhất trên toàn AWS.

### Bước 2. Chạy crawler (local hoặc qua Lambda/EventBridge)
```bash
cd crawler
pip install -r requirements.txt
python tiki_crawler.py --pages 3 --upload --bucket <prefix>-raw
```
Ghi dữ liệu NDJSON vào `raw/source=tiki/dt=YYYY-MM-DD/` trên S3 (hoặc vào
`./output/` ở local nếu bỏ `--upload`). **Chạy lại mỗi ngày** (thủ công
hoặc để EventBridge tự chạy) để có đủ snapshot cho việc tính tăng trưởng —
chạy một lần duy nhất sẽ không đủ dữ liệu để phân tích/huấn luyện model.

### Bước 3. Chạy pipeline xử lý dữ liệu
```bash
aws stepfunctions start-execution --state-machine-arn <arn lấy từ output của cdk deploy>
```
State machine `product-pipeline` sẽ chạy lần lượt `raw-to-stage` rồi
`stage-to-analytics`.

### Bước 4. Truy vấn bằng Athena
Glue job tự tạo/cập nhật bảng `product_analytics.products`. Vào Athena,
chọn workgroup ghi kết quả tại `<prefix>-athena-results` và truy vấn trực
tiếp bảng này, ví dụ:
```sql
SELECT name, category, sold_growth_rate, review_growth, potential_score
FROM product_analytics.products
WHERE year_month = '2026-09'
ORDER BY potential_score DESC
LIMIT 20;
```

### Bước 5. Dựng dashboard
Tạo dataset QuickSight từ bảng Athena `product_analytics.products`, làm
theo hướng dẫn chi tiết tại [dashboard/README.md](dashboard/README.md).

### Bước 6. Huấn luyện mô hình dự báo sản phẩm tiềm năng
```bash
cd ml
pip install -r requirements.txt
python train_potential_model.py --database product_analytics --table products
```

## 6. Ước lượng dung lượng lưu trữ (điền sau khi crawl vài ngày)

| Chỉ số | Giá trị |
|---|---|
| Số sản phẩm theo dõi/ngành hàng | Chưa có (TBD) |
| Số ngành hàng | Chưa có (TBD) |
| Kích thước trung bình 1 snapshot | Chưa có (TBD) |
| Thời gian lưu trữ (bản demo) | Chưa có (TBD) |
| Dung lượng Raw mục tiêu | Chưa có (TBD) GB |
| Dung lượng Analytics (Iceberg, đã nén) | Chưa có (TBD) GB |

Lưu ý: khác với dữ liệu "trạng thái hiện tại", bảng Stage ở đây **tăng gần
như tuyến tính theo số ngày retention** vì mỗi ngày thêm một snapshot mới
cho mỗi sản phẩm — cách tính chi tiết có trong `docs/ARCHITECTURE.md`.
