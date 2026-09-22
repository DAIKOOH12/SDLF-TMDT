# Hướng dẫn chạy từng bước (Runbook)

File này liệt kê **chính xác lệnh cần chạy, theo đúng thứ tự**, để đưa dự án
từ trạng thái code (repo hiện tại) lên chạy thật trên AWS. Xem
[README.md](../README.md) để hiểu kiến trúc/lý do thiết kế;
[ARCHITECTURE.md](ARCHITECTURE.md) để hiểu schema chi tiết.

## Giá trị cố định của account này

Đã điền sẵn theo account/region/prefix đang dùng — nếu bạn đổi `PREFIX`
trong `infra/app.py` hoặc deploy sang account/region khác, thay lại các giá
trị này cho khớp.

| Giá trị | Nội dung |
|---|---|
| AWS Account | `770880870430` |
| Region | `ap-southeast-1` |
| Prefix | `product-analytics-demo` |
| Bucket Raw | `product-analytics-demo-raw` |
| Bucket Stage | `product-analytics-demo-stage` |
| Bucket Analytics | `product-analytics-demo-analytics` |
| Bucket Scripts | `product-analytics-demo-scripts` |
| Bucket Athena results | `product-analytics-demo-athena-results` |
| Athena Workgroup | `product-analytics-demo-athena` |
| Glue Database (Stage) | `product_stage` |
| Glue Database (Analytics) | `product_analytics` |
| Glue Job 1 | `raw-to-stage` |
| Glue Job 2 | `stage-to-analytics` |
| Lambda crawler | `product-analytics-demo-crawler` |
| EventBridge rule (crawl hàng ngày) | `product-analytics-demo-daily-crawl` |
| Step Functions state machine | `product-pipeline` |
| Step Functions ARN | `arn:aws:states:ap-southeast-1:770880870430:stateMachine:product-pipeline` |

Đánh dấu ✅ sau mỗi bước đã làm xong và kiểm tra được kết quả — đừng làm
bước sau khi bước trước còn chưa chắc chắn đúng, vì lỗi sẽ dồn xuống rất
khó debug ở Glue/Athena.

---

## Bước 0 — Chuẩn bị môi trường

```bash
# Kiểm tra đã có sẵn
python --version     # cần 3.11+
node --version        # cần 18+
aws --version

# Cài CDK CLI (chỉ cần 1 lần)
npm install -g aws-cdk

# Cấu hình AWS credentials (nếu chưa)
aws configure
```

> Không cần Docker — Lambda crawler được đóng gói bằng script Python thuần
> (`crawler/build_lambda.py`), không dùng Docker image để bundling.

Kiểm tra: `aws sts get-caller-identity` trả về đúng account/region bạn dự
định dùng.

---

## Bước 1 — Xác minh API Tiki còn đúng như đã khảo sát

API là **không chính thức**, có thể đổi format bất cứ lúc nào. Trước khi
chạy gì khác, xác minh lại nhanh:

1. Mở `https://tiki.vn/dien-thoai-may-tinh-bang/c1789`, F12 → Network →
   filter Fetch/XHR → F5 → tìm request `listings?...`.
2. So khớp field trong Response với những gì `crawler/tiki_crawler.py` đang
   đọc (`price`, `original_price`, `discount_rate`, `rating_average`,
   `review_count`, `quantity_sold`, `seller_id`).
3. Nếu bạn dùng thêm category `1846` (đồ gia dụng) hoặc `931` (thời trang
   nữ) trong `crawler/config.py` — mở đúng 2 trang danh mục đó, xác nhận
   `category` id và `urlKey` trong request khớp với những gì đang khai báo.

---

## Bước 2 — Chạy thử crawler ở local (chưa cần AWS)

```bash
cd crawler
pip install -r requirements.txt
python tiki_crawler.py --pages 1
```

Kiểm tra: file JSON sinh ra tại `crawler/output/source=tiki/dt=<hôm nay>/`.
Mở file, xác nhận không có dòng nào `price` hoặc `product_id` bị `null`.

```bash
# Windows PowerShell
Get-Content .\output\source=tiki\dt=*\*.jsonl | Select-Object -First 2
```

---

## Bước 3 — Deploy hạ tầng AWS (S3, Glue, Step Functions)

```bash
cd infra
python -m venv .venv
.venv\Scripts\activate          # PowerShell; Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

**Trước khi deploy**: `PREFIX` trong `infra/app.py` đang để
`product-analytics-demo` — nếu tên này đã unique với bạn thì giữ nguyên
(khớp với toàn bộ giá trị đã điền sẵn ở bảng trên); nếu bucket bị báo trùng
tên khi deploy, đổi `PREFIX` thành chuỗi khác rồi thay lại tương ứng trong
bảng trên và các lệnh bên dưới.

**Trước khi `cdk deploy`**, build gói Lambda cho crawler (script Python
thuần, không cần Docker):
```bash
python ../crawler/build_lambda.py
```
Lệnh này tạo `infra/lambda_build/crawler/` — chạy lại **mỗi khi bạn sửa
code trong `crawler/`**, vì `pipeline_stack.py` chỉ đóng gói đúng những gì
đang có sẵn trong thư mục này tại thời điểm `cdk deploy`, không tự rebuild.

```bash
cdk bootstrap     # chỉ chạy 1 lần / account+region
cdk deploy --all
```

CDK sẽ hỏi xác nhận IAM policy trước khi tạo — gõ `y`. Quá trình này mất
vài phút (chủ yếu do tạo Glue Job).

**Sau khi `cdk deploy --all` chạy xong**, upload 2 script PySpark lên bucket
scripts (không dùng CDK `BucketDeployment` vì construct đó hiện đang lỗi
trên nhiều account/region do bug tương thích Python 3.9/urllib3 trong layer
awscli nội bộ của CDK — lỗi từ phía AWS, không phải do repo này):
```bash
pip install -r ../glue_jobs/requirements.txt   # nếu venv này chưa có boto3
python ../glue_jobs/upload_scripts.py --bucket product-analytics-demo-scripts
```
Chạy lại lệnh này **mỗi khi bạn sửa code trong `glue_jobs/clean_transform/`**
— Glue luôn đọc script mới nhất từ S3 mỗi lần job chạy, không cần
`cdk deploy` lại chỉ vì sửa script.

Kiểm tra sau khi deploy xong:
- Console S3: có đủ 5 bucket `product-analytics-demo-raw/-stage/-analytics/-scripts/-athena-results`
- Console S3 → `product-analytics-demo-scripts/scripts/`: có `raw_to_stage.py`, `stage_to_analytics.py`
- Console Glue → Databases: có `product_stage`, `product_analytics`
- Console Glue → Jobs: có `raw-to-stage`, `stage-to-analytics`
- Console Athena → Workgroups: có `product-analytics-demo-athena`, output location trỏ đúng `s3://product-analytics-demo-athena-results/`
- Console Step Functions: có state machine `product-pipeline`
  (ARN: `arn:aws:states:ap-southeast-1:770880870430:stateMachine:product-pipeline` — dùng ở Bước 6)
- Console Lambda: có function `product-analytics-demo-crawler`
- Console EventBridge: có rule `product-analytics-demo-daily-crawl`

---

## Bước 4 — Crawl dữ liệu thật lên S3 Raw

```bash
cd crawler
python tiki_crawler.py --pages 3 --upload --bucket product-analytics-demo-raw
```

Kiểm tra:
```bash
aws s3 ls s3://product-analytics-demo-raw/raw/source=tiki/ --recursive
```

**Quan trọng**: chạy lại lệnh này **mỗi ngày** (thủ công trong lúc chưa bật
lịch tự động, hoặc để EventBridge tự chạy — xem Bước 5) trong ít nhất
vài ngày liên tiếp trước khi qua Bước 6, vì `sold_growth_rate` cần ít nhất
2 snapshot của cùng sản phẩm mới tính ra được số khác NULL.

---

## Bước 5 — Bật crawl tự động theo lịch (tùy chọn, nên bật sớm)

Đã cấu hình sẵn trong `infra/infra/pipeline_stack.py`: EventBridge gọi
Lambda crawler mỗi ngày lúc 18:00 UTC. Không cần làm gì thêm sau khi
`cdk deploy` — kiểm tra bằng cách:

```bash
aws events describe-rule --name product-analytics-demo-daily-crawl
```

Theo dõi lỗi (nếu có) tại CloudWatch Logs → log group
`/aws/lambda/product-analytics-demo-crawler`.

---

## Bước 6 — Chạy pipeline làm sạch/biến đổi dữ liệu

Sau khi đã có **ít nhất 2 ngày** dữ liệu raw:

```bash
aws stepfunctions start-execution --state-machine-arn arn:aws:states:ap-southeast-1:770880870430:stateMachine:product-pipeline
```

Theo dõi tiến trình:
```bash
aws stepfunctions describe-execution --execution-arn <execution arn trả về ở lệnh trên>
```
Hoặc xem trực tiếp trên Console Step Functions (dễ debug hơn — thấy được
Glue job nào lỗi, log chi tiết).

Chạy lại lệnh `start-execution` này **mỗi lần muốn cập nhật dữ liệu Stage/
Analytics** (thủ công, hoặc tự thêm 1 EventBridge rule khác nếu muốn tự
động hoàn toàn).

---

## Bước 7 — Kiểm tra dữ liệu bằng Athena

Vào Athena Console, chọn workgroup **`product-analytics-demo-athena`**
(kết quả query tự động ghi vào `s3://product-analytics-demo-athena-results/`),
chạy thử:

```sql
-- Kiểm tra bảng Stage có dữ liệu
SELECT * FROM product_stage.products LIMIT 10;

-- Kiểm tra bảng Analytics đã tính growth
SELECT name, category, crawl_date, quantity_sold, sold_growth_rate,
       review_growth, potential_score
FROM product_analytics.products
ORDER BY crawl_date DESC
LIMIT 20;

-- Top sản phẩm tiềm năng theo ngành hàng, tháng hiện tại
SELECT category, name, sold_growth_rate, potential_score
FROM product_analytics.products
WHERE year_month = date_format(current_date, '%Y-%m')
ORDER BY potential_score DESC
LIMIT 20;
```

Nếu `sold_growth_rate` toàn `NULL`: bình thường ở **lần chạy đầu tiên**
(chưa có snapshot trước đó để so sánh) — chạy thêm Bước 4 + Bước 6 vào
ngày hôm sau sẽ có số.

---

## Bước 8 — Dựng dashboard QuickSight

Làm theo checklist chi tiết trong [dashboard/README.md](../dashboard/README.md):
1. Tạo data source Athena trong QuickSight.
2. Tạo dataset trỏ vào `product_analytics.products`.
3. Dựng các biểu đồ: bảng xếp hạng tiềm năng, xu hướng tăng trưởng theo
   ngành hàng, phân phối growth rate, tương quan giảm giá–tăng trưởng.
4. Publish thành **Dashboard** (không chỉ Analysis) để chia sẻ được.

---

## Bước 9 — Huấn luyện mô hình dự báo sản phẩm tiềm năng

Chỉ chạy khi đã có **đủ nhiều ngày dữ liệu** (khuyến nghị ≥ 7–14 ngày để
nhãn top-quantile theo tháng có ý nghĩa thống kê):

```bash
cd ml
pip install -r requirements.txt
python train_potential_model.py --database product_analytics --table products
```

Kiểm tra: log in ra ROC-AUC và classification report; file
`potential_model.joblib` được tạo ra trong thư mục `ml/`.

---

## Bước 10 — Dọn dẹp (khi demo/nộp bài xong, tránh phát sinh phí AWS)

```bash
cd infra
cdk destroy --all
```

**Lưu ý**: các bucket S3 dùng `RemovalPolicy.RETAIN` (xem
`storage_stack.py`) nên sẽ **không** bị xóa tự động — vào Console S3 xóa
tay nếu chắc chắn không cần dữ liệu nữa. Đây là chủ đích: tránh mất dữ liệu
nếu `cdk destroy` chạy nhầm.

---

## Bảng tóm tắt thứ tự

| # | Việc | Cần lặp lại? |
|---|---|---|
| 0 | Cài môi trường | 1 lần |
| 1 | Xác minh API Tiki | 1 lần (hoặc khi thấy dữ liệu bất thường) |
| 2 | Test crawler local | 1 lần |
| 3 | `cdk deploy --all` | 1 lần (hoặc khi sửa infra) |
| 4 | Crawl lên S3 (`--upload`) | **Hàng ngày** |
| 5 | Bật lịch tự động | 1 lần |
| 6 | `start-execution` Step Functions | Mỗi lần muốn cập nhật Stage/Analytics |
| 7 | Query Athena kiểm tra | Khi cần xem dữ liệu |
| 8 | Dựng dashboard | 1 lần, chỉnh sửa dần |
| 9 | Train ML | Khi đã đủ dữ liệu lịch sử |
| 10 | `cdk destroy` | Khi kết thúc dự án |
