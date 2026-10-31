# Kiểm tra bàn giao — 31/10/2026

## Phạm vi bản cập nhật

Đã thay hoàn toàn bộ giả lập bằng **Shera Video 14/33 và Auntie Video 5**.
Snapshot gồm 2 dự án cha, 3 video con, 23 cảnh, 48 clip timeline và 107 media duy nhất.
Tổng 652 record gồm child tables. Media được lấy từ các dependency của đúng ba bản
video local đã chọn; không thay đổi dữ liệu nguồn hoặc khởi chạy generation.

## Môi trường

- JoyMedia: `0.0.1`; commit nền `ca5b0104`; file chưa commit được ghi hash trong manifest.
- Frappe: `16.33.0`, commit `33bf510b17afcaaa857ed38b921d8e9e50dcd232`.
- Bench CLI: `5.31.0`; Python: `3.14.7`; Node: `24.20.0`; npm: `11.19.0`.
- MariaDB server dùng kiểm tra: `11.8.9`.

## Kiểm tra snapshot mới

| Kiểm tra | Kết quả |
| --- | --- |
| 8 test restore | Đạt: mở shelves/workspace, giữ timeline, chạy lại giữ chỉnh sửa, chặn cờ tắt/Guest, chặn owner xung đột, rollback khi lỗi, chặn Link thiếu và hash sai |
| Schema và Link của 652 record | Đạt, mọi Link trong snapshot được phân giải, không nhập user hoặc job |
| SQL INSERT trên MariaDB hiện tại | Đạt, 652 record; sau SQL, loader bỏ qua database và khôi phục media |
| API project cards | Đúng 2 card thuộc bộ bàn giao, số video lần lượt 2 và 1 |
| API shelves/workspace | Shera 14/33, Auntie 5; mở được storyboard và timeline, không gọi HTTP service ngoài |
| Frame timing và take references | Khớp snapshot; các Shot kiểm tra được liên kết selected output |
| 107 media files | Khớp SHA-256; 108 File record có thể dùng chung bytes |
| Ba MP4 cuối so với nguồn | SHA-256 trùng tuyệt đối, ffprobe đọc được video stream |
| Thời lượng MP4 | Shera 14: 30.000 s; Shera 33: 30.000 s; Auntie 5: 30.016 s |
| Rollback thử nghiệm | Không còn record snapshot và không còn file `jm-demo-*` tạo tạm trên site nguồn |
| Dò cấu hình nhạy cảm trong snapshot | Không có giá trị secret/credential/endpoint ở các khóa được quét; không có chuỗi email hoặc đường dẫn `/home`, `/workspace`, `/srv` |
| Ruff check/format cho code bàn giao và test | Đạt |
| ZIP CRC, allowlist, manifest, media hashes và SHA256SUMS | Kiểm tra trên gói cuối |

Các kiểm tra database dùng transaction trên schema hiện có; toàn bộ dữ liệu thử được
rollback. Kiểm tra SQL bỏ BEGIN/COMMIT để không commit snapshot vào site nguồn.
Loader là công cụ restore trực tiếp có kiểm tra schema/Links, không chạy các hook tạo
mới có thể thay timing/version. Đường nạp JSON và đường SQL + media đều đã kiểm tra.

## Kiểm tra mã nguồn đã thực hiện ở lượt đóng gói trước

Frontend không thay đổi trong bản cập nhật dữ liệu này. Bản giải nén riêng trước đó
đã qua `npm ci` (267 packages), 16/16 test Node và `npm run build`; template frontend
được tạo thành công. App layout, Python/JSON syntax và đóng gói lại khi không có `.git`
đã được kiểm tra. Bộ test dữ liệu giả lập cũ đã được thay bằng 8 test snapshot ở trên.

## Cài mới và kiểm tra bằng trình duyệt

Đã giải nén ZIP vào thư mục riêng, tạo Git repository cục bộ và cài **Bench 5.31.0**
trong venv mới. `bench init` tải Frappe từ GitHub bằng tag cố định **v16.33.0**;
không dùng lại framework checkout, Python environment hoặc database của site nguồn.
Tạo database trống và mật khẩu Administrator mới cho `joymedia-demo.localhost`.
MariaDB là service có sẵn trong môi trường kiểm thử; database/user kiểm thử được tạo riêng.
Redis của Bench chạy độc lập ở cổng 11000/13000. Không sao chép site config nguồn.

| Bước | Kết quả |
| --- | --- |
| Tạo venv CLI và `bench init` | Đạt, tải/install/build Frappe từ tag v16.33.0 |
| `bench get-app` từ source ZIP và cài extras | Đạt |
| Tạo site/database trống, install-app, migrate | Đạt sau khi sửa thứ tự/lệnh trong README |
| `bench build`, `npm ci`, `npm run build` | Đạt trong môi trường mới |
| Nạp demo bằng lệnh CLI | 652 record, 2 dự án, 3 video, 107 media; cờ nạp được tắt sau đó |
| Đăng nhập bằng form trình duyệt | HTTP 200, Administrator đăng nhập thành công |
| Trang danh sách dự án | Hiển thị Shera với 2 video và Auntie với 1 video |
| Mở workspace của 3 video | Đạt, giao diện và các request hoàn tất không có lỗi trong lượt kiểm tra cuối |
| Phát MP4 trong trình duyệt | Cả 3 video phát, thời gian phát tăng |
| Tua video | Cả 3 video tua được đến giây thứ 10 |
| HTTP Range có đăng nhập | Cả 3 MP4 trả HTTP 206, đúng 1.024 byte cho yêu cầu bytes=0-1023 |

Các điểm được phát hiện và sửa trực tiếp trong hướng dẫn:

1. Sau `get-app` từ ZIP, cần `ensure_bench_app.py` để tránh `App joymedia not in apps.txt`.
2. Chạy `bench start` ở terminal thứ nhất trước khi chạy `migrate` ở terminal thứ hai;
   nếu không, Redis của Bench chưa chạy.
3. Cờ CLI dùng `1/0 --parse`; Frappe ở phiên bản này không nhận `true/false --parse`.
4. Hướng dẫn dev/demo bật `developer_mode 1` để frontend dùng đúng cổng Socket.IO.
5. Cố định tag framework thay vì dựa vào nhánh `version-16` có thể thay đổi.

## Giới hạn

- Kết quả trên xác nhận cài app và mở/phát bộ demo trên môi trường Linux với các
  dependency hệ thống đã chuẩn bị. Chưa tự động cài toàn bộ hệ điều hành/phần mềm
  nền trên mọi bản Linux/Windows/macOS. Thực hiện đủ bước chuẩn bị máy trong README.
- Chưa chạy lại toàn bộ server suite hoặc mọi luồng browser E2E. Đã kiểm tra thực tế
  luồng đăng nhập, danh sách dự án, mở ba workspace, phát/tua video và HTTP 206.
- Chưa render/export lại bằng GPU hoặc triển khai production. MP4 có sẵn không chứng
  minh hạ tầng mới có đủ model/custom node để tái tạo. Lịch sử job và chữ ký duyệt/release
  không được mang sang site nhận; cần duyệt lại khi thực hiện generation mới.
- Vite báo chunk JS lớn hơn 500 kB nhưng build thành công.
- Scanner secret có phạm vi giới hạn, không thay cho audit bảo mật toàn ứng dụng.
