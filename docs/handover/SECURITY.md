# Bảo mật và phạm vi bàn giao

## File được đưa vào ZIP

`scripts/build_handover.py` dùng allowlist mã nguồn app, deploy, scripts, tài liệu
bàn giao, giấy phép và snapshot demo Shera/Auntie cùng media được chọn. Đọc working tree hiện tại, không đọc Git history
để đóng gói. File phát sinh ngoài allowlist không tự lọt vào gói.

Đã loại khỏi bản bàn giao: `env/`, `.venv/`, `node_modules/`, `.git/`, `sites/`,
`logs/`, `config/` runtime, Procfile cục bộ, upstream/research, cache/bytecode,
`.DS_Store`, test artifacts, file frontend build và `_joymedia.html` được sinh từ build. Chỉ media được liệt kê
trong `joymedia/demo/manifest.json` mới thuộc snapshot bàn giao, không sao chép toàn bộ site files.
Các báo cáo khách hàng/phiên chạy cũ và cấu hình partner thực không thuộc allowlist docs.
Không xóa môi trường, site, dữ liệu hoặc dependencies đang dùng trên máy phát triển;
việc dọn sạch thực hiện trên tập file xuất ra ZIP.

Giữ nguyên package-lock, schema, migrations, fonts, vendor licenses, workflow graph
và model contracts vì chúng là đầu vào cần thiết để cài/build app, không phải file rác.
Tài liệu vận hành cũ được giữ một phần để tham khảo code; hướng dẫn chuẩn của gói là
`README.md` và `docs/handover/`. Một số liên kết báo cáo lịch sử trong tài liệu
cũ không có trong gói vì những báo cáo đó nằm ngoài phạm vi bàn giao.

## Secret và cấu hình

- Cấu hình thật của site, encryption key, password DB và SSH keys không được đóng gói.
  107 file media thuộc ba video được người dùng yêu cầu là ngoại lệ có chủ đích;
  mỗi file có SHA-256 và được khôi phục ở chế độ private, owner Administrator.
- Mẫu `site_config.example.json` dùng địa chỉ loopback, model placeholder, khóa trống.
  `.env` không phải cơ chế cấu hình mà app này tự nạp.
- Không đưa key vào frontend, Git, ZIP, ảnh chụp/log, CLI arguments hoặc shell history.
  Nhập mật khẩu tương tác; sửa cấu hình server bằng editor có phân quyền.
- Mỗi bên nhận tạo DB/password/encryption key riêng. Backup production cần khóa mã hóa
  của chính site đó, lưu tách khỏi bản mã nguồn và giới hạn người truy cập.
- `joymedia_allow_demo_data` mặc định tắt; loader demo chỉ cho Administrator và
  không được expose qua HTTP whitelist. `allow_tests` chỉ bật ở site test riêng.
- Sau cài đặt, kiểm tra quyền JoyMedia User/reviewer, tắt public signup theo nhu cầu,
  thiết lập HTTPS, backup và process manager trước khi vận hành production.

Script kiểm tra mẫu private key/token/URL có credential và đối chiếu các giá trị
secret đủ dài trong cấu hình site hiện có với bytes của các file xuất. Khi phát hiện,
nó dừng và chỉ báo tên file/loại lỗi, không in secret. Đây là kiểm tra gói bàn giao,
không phải chứng nhận đã audit toàn bộ lỗ hổng hay dò được mọi dạng secret.
Không đưa tài khoản của môi trường demo cũ vào tài liệu này.

## Kiểm tra tính toàn vẹn

ZIP có `MANIFEST.json` ghi commit nền, kích thước và hash từng source file;
`SHA256SUMS` kiểm tra source + manifest. File `.zip.sha256` bên cạnh kiểm tra cả ZIP.
Manifest phản ánh cả file mới/chưa commit trong working tree, vì vậy commit nền
không tự nó đại diện cho toàn bộ nội dung gói. Không có bước tự push/publish/deploy.

## Phạm vi snapshot video

Chỉ lấy dự án cha, ba bản video đã chọn, storyboard, timeline, media, nguồn media dẫn xuất
và workflow/pipeline cần tham chiếu. Không lấy các bản thử nghiệm khác, tài khoản, session,
partner policy, bình luận người dùng, lịch sử Run/Task/Attempt hoặc kết quả phê duyệt cũ.
Mọi owner/modified_by được chuẩn hóa thành Administrator của site mới. Đường dẫn media
được đổi sang tên theo SHA-256; không giữ đường dẫn máy chủ nguồn trong cấu hình.
Media có nguồn ở dự án ngoài phạm vi được đưa về Library để không tạo thêm dự án.

Các chữ ký approval/release và metadata phân tích cũ bị loại bỏ, không coi tài khoản
nhận bàn giao là người đã duyệt nội dung. Loader là công cụ restore dành cho Administrator:
kiểm tra schema, Link và checksum trước rồi ghi trực tiếp để giữ version/timing lịch sử,
không chạy controller hooks có thể đánh lại số version hoặc sắp xếp lại timeline.
Không đăng ký loader vào HTTP whitelist hay install/migrate hooks.

## Kiểm tra file tự sinh trước bàn giao

Bộ lọc áp dụng cả với file đã được Git theo dõi và khi đóng gói lại source đã giải nén.
Loại `node_modules`, env/venv, build/dist/out, bundle frontend, Python bytecode,
cache của Ruff/Pytest/Mypy/Vite, coverage, báo cáo Playwright, thư mục IDE,
file tạm/backup/swap, source map, metadata hệ điều hành và các gói ZIP/wheel cũ.
Sau khi tạo ZIP, script đối chiếu lại từng entry với danh sách file đã duyệt;
không chấp nhận file ngoài danh sách hoặc file tự sinh thuộc bộ lọc.

Source test/fixture, migration, lockfile, font, vendor license và 107 media demo có
trong manifest là thành phần bàn giao cần giữ. Các MP4 của demo là dữ liệu người dùng
yêu cầu bàn giao, không phải build artifact để xóa. Thư mục runtime của máy phát triển
được giữ nguyên; không đưa vào ZIP.
