# Database và media mẫu — Shera / Auntie

Snapshot lấy từ đúng các bản video được chọn cho demo triển khai:

| Dự án cha | Video | Bản nguồn | Bản nhập |
| --- | --- | --- | --- |
| Shera (`PRJ-02501`) | 14 | `PRJ-02558` | `JM-DEMO-PRJ-02558` |
| Shera (`PRJ-02501`) | 33 | `PRJ-02586` | `JM-DEMO-PRJ-02586` |
| T-Shirt Auntie (`PRJ-02559`) | 5 | `PRJ-02563` | `JM-DEMO-PRJ-02563` |

Giao diện có **2 dự án / 3 video**. Database có 5 Media Project (2 cha + 3 video con),
23 Shot, 48 Timeline Clip, 132 Asset Version, 131 Media Asset và các bảng tham chiếu,
workflow/pipeline liên quan. Tổng cộng **652 record** gồm child rows; **108 File record**
trỏ tới **107 file media duy nhất**, tổng **195.075.524 byte** (khoảng 186 MiB).
Video đang chọn mặc định: Shera 33 và Auntie 5. Dự án cha chỉ gom tài nguyên,
không mang storyboard/output riêng để tránh hiển thị thêm video thứ tư/thứ năm.

- `joymedia/demo/records.json`: snapshot document, các ID dùng tiền tố `JM-DEMO-`.
- `joymedia/demo/manifest.json`: danh sách video, số record và SHA-256 từng media.
- `joymedia/demo/media/`: MP4 thành phẩm/take, ảnh, âm thanh và workbook liên quan.
- `database/sample.sql`: các INSERT tương đương, gồm cả child rows và File metadata.
- `joymedia/demo/seed.py`: loader khôi phục database và media, không gọi AI.

Không chứa bộ giả lập Ceramic Cup/Canvas Bag. Không sao chép tài khoản, mật khẩu,
site config, session, lịch sử generation hoặc các bản video khác trong danh sách dự án. Media nguồn
ngoài ba bản video được giữ khi là dependency và đưa về Library. Các chữ ký approval,
release evidence và kết quả phân tích cũ bị bỏ; storyboard cần được duyệt lại khi render mới.

## Cách nạp khuyến nghị

Tạo site demo riêng, cài app và migrate theo [hướng dẫn](../docs/handover/INSTALLATION.md).
Cần khoảng 200 MB trống cho media được sao chép, ngoài ZIP và source đã giải nén.
Từ thư mục Bench:

```sh
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 1 --parse
bench --site joymedia-demo.localhost execute joymedia.demo.seed.load
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 0 --parse
bench --site joymedia-demo.localhost clear-cache
```

Loader yêu cầu Administrator và cờ bật tường minh. Nó kiểm tra toàn bộ schema/Link,
checksum nguồn, file đích và ID xung đột trước khi ghi. Files dùng tên theo hash trong
`sites/<site>/private/files/`, mode 600, owner trong database là Administrator.
Sau đó restore trực tiếp các record trong transaction để giữ số version, thứ tự và
frame timing; không chạy các controller hooks tạo mới/đánh lại số/tự sắp timeline.
Nếu lỗi, rollback record mới và xóa các file vừa sao chép. Không tạo user hoặc job GPU.
Chạy từng lượt nạp, không chạy đồng thời hai loader trên cùng site.

Nạp lại một bộ đầy đủ: giữ chỉnh sửa database và chép lại media thiếu nếu checksum hợp lệ.
ID có owner hoặc liên kết định danh khác sẽ bị từ chối. Bộ dữ liệu chỉ tồn tại một phần
cũng bị từ chối: dùng site demo sạch hoặc khôi phục backup, không tự ghi đè/merge dữ liệu.

Đăng nhập Administrator, mở `/joymedia/projects`: Shera có Video 14/33, Auntie có Video 5.
Có thể xem MP4, storyboard và timeline khi chưa cài AI. Để render hoặc export lại,
cần model, workflow, service và worker tương thích; snapshot không tự bật những dịch vụ đó.

## Nạp bằng SQL (phương án thay thế)

`sample.sql` là **data-only snapshot cho MariaDB**, không dùng với `bench restore`.
Schema do Frappe và `install-app joymedia`/`migrate` tạo. Chỉ trên site demo mới, chưa nạp JSON:

```sh
bench --site joymedia-demo.localhost mariadb < apps/joymedia/database/sample.sql
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 1 --parse
bench --site joymedia-demo.localhost execute joymedia.demo.seed.load
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 0 --parse
bench --site joymedia-demo.localhost clear-cache
```

Bước loader sau SQL vẫn bắt buộc để kiểm tra và chép media; kết quả database là
`created: 0, skipped: 652`. SQL không chứa binary media, không DROP/DELETE/REPLACE,
có transaction và INSERT thông thường. Không nạp SQL lần hai và không dùng `--force`
để bỏ qua lỗi. Cách nạp JSON ở trên là lựa chọn khuyến nghị cho người nhận.

## Kiểm tra

Trong `bench --site joymedia-demo.localhost console`:

```python
from joymedia.services.project.versions import get_videos
[(v['label'], v['video']) for v in get_videos('JM-DEMO-PRJ-02501')['videos']]
[(v['label'], v['video']) for v in get_videos('JM-DEMO-PRJ-02559')['videos']]
```

Kết quả tương ứng 2 và 1 video, mỗi video có đường dẫn `/private/files/jm-demo-...mp4`.
Hash trong manifest phải khớp từng file; riêng ba MP4 cuối giữ nguyên byte từ bản nguồn.
Nguồn local không bị chỉnh sửa trong quá trình xuất hoặc các lần kiểm thử rollback.
