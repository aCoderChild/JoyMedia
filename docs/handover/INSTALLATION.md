# Cài đặt và khởi chạy

Hướng dẫn từng bước bằng tiếng Việt nằm trực tiếp trong [README chính](../../README.md#cai-dat-va-khoi-chay).
Tài liệu này bổ sung các chi tiết cấu hình AI và vận hành.

## 1. Điều kiện và phiên bản

Môi trường repository tại thời điểm bàn giao dùng Frappe **16.33.0**, Python
**3.14.7**, Node **24.20.0**. CI hiện có cả tổ hợp Python 3.12/Frappe 15/Node 20
và Python 3.14/Frappe 16/Node 24. Ưu tiên Frappe 16 cho gói này; kết quả thực sự
đã kiểm tra được ghi riêng trong [VALIDATION.md](VALIDATION.md).

Cần Linux (hoặc WSL2), Git, Python 3.14 + headers/venv, Node 24, Yarn classic,
MariaDB có charset utf8mb4, Redis, FFmpeg/ffprobe và công cụ biên dịch.
Cài các dịch vụ theo hệ điều hành, bật MariaDB và Redis trước khi tạo Bench.
Cần Internet để tải framework/dependencies. ZIP không phải bộ cài offline.
Không dùng thư mục ZIP làm thư mục runtime Bench.

## 2. Chuẩn bị app từ ZIP

ZIP không mang `.git`. Tạo repository local để Bench có thể clone app:

```sh
cd /absolute/path/joymedia-v0.0.1-handover-20261031
python3.14 scripts/verify_app_layout.py
export JOYMEDIA_SOURCE="$(pwd)"
git init -b handover
git add .
git -c user.name='Handover' -c user.email='handover@example.invalid' commit -m 'Import handover source'
```

Dùng cùng terminal để giữ biến `JOYMEDIA_SOURCE`. Tạo môi trường CLI riêng và Bench
mới tại `~/joymedia-bench`, tách khỏi source (đường dẫn ví dụ cần thay bằng đường dẫn thật):

```sh
python3.14 -m venv ~/.venvs/joymedia-bench-cli
~/.venvs/joymedia-bench-cli/bin/pip install 'frappe-bench==5.31.0'
export PATH="$HOME/.venvs/joymedia-bench-cli/bin:$PATH"
cd "$HOME"
bench init --python "$(command -v python3.14)" --frappe-branch v16.33.0 joymedia-bench
cd joymedia-bench
bench get-app --skip-assets joymedia "$JOYMEDIA_SOURCE"
python3.14 apps/joymedia/scripts/ensure_bench_app.py sites/apps.txt joymedia
./env/bin/pip install --only-binary=opencv-python-headless -e 'apps/joymedia[tracking,cinematography,narration]'
bench new-site joymedia-demo.localhost
bench --site joymedia-demo.localhost install-app joymedia
bench --site joymedia-demo.localhost set-config developer_mode 1 --parse
bench use joymedia-demo.localhost
bench start
```

Giữ terminal trên chạy. Mở **terminal thứ hai** để migrate/build và nạp demo:

```sh
export PATH="$HOME/.venvs/joymedia-bench-cli/bin:$PATH"
cd ~/joymedia-bench
bench --site joymedia-demo.localhost migrate
bench build
cd apps/joymedia/joymedia/frontend
npm ci
npm run build
cd ../../../..
```

`bench new-site` hỏi thông tin quản trị MariaDB và mật khẩu Administrator mới.
Nhập tương tác, không ghi mật khẩu vào mã nguồn hay lệnh shell. Tag `v16.33.0`
đã được cố định để tái lập cùng phiên bản framework. `ensure_bench_app.py` phải
chạy trước khi cài app từ ZIP. Giữ `bench start` chạy khi thực hiện migrate.
Nếu MariaDB ở container/máy khác, thêm `--db-host <địa-chỉ>` vào `bench new-site`.

`npm ci` dùng `package-lock.json`; không xóa lockfile. `npm run build` sinh
`joymedia/public/frontend` và `joymedia/templates/pages/_joymedia.html`.
Nếu bỏ qua bước này route `/joymedia` chưa có template để hiển thị.
Hai tầng `joymedia/joymedia` là cấu trúc module Frappe, phải giữ nguyên.

## 3. Nạp demo và mở giao diện

Từ thư mục Bench:

```sh
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 1 --parse
bench --site joymedia-demo.localhost execute joymedia.demo.seed.load
bench --site joymedia-demo.localhost set-config joymedia_allow_demo_data 0 --parse
bench --site joymedia-demo.localhost clear-cache
```

Giữ `bench start` ở terminal đầu tiên đang chạy. Truy cập `http://joymedia-demo.localhost:8000/login`, đăng nhập `Administrator`
với mật khẩu vừa tạo; mở `http://joymedia-demo.localhost:8000/joymedia/projects`.
Nếu tên miền không resolve, thêm `127.0.0.1 joymedia-demo.localhost` vào hosts.
Danh sách có dự án giấy **Shera** với **Video 14, Video 33** và **T-Shirt Auntie**
với **Video 5**. Mở storyboard/timeline và xem MP4 có sẵn; chưa bấm tạo hoặc xuất lại
video khi các dịch vụ AI chưa được cài đặt. Lệnh nạp sao chép 107 file media vào
`sites/<site>/private/files/`, cần khoảng 200 MB dung lượng trống ngoài dung lượng ZIP/source.
Lệnh có thể chạy lại để xác minh/khôi phục media thiếu, giữ nguyên chỉnh sửa database;
nếu chỉ một phần record đã tồn tại, loader dừng để tránh ghép dữ liệu không đầy đủ.
Xem [database](../../database/README.md) nếu cần import bằng SQL.

## 4. Cấu hình AI và hàng đợi khi cần sinh video

Mẫu [site_config.example.json](site_config.example.json) chỉ có các giá trị ví dụ.
App đọc `frappe.conf`, không tự đọc `.env`. Sửa/merge các khóa ứng dụng cần thiết
vào `sites/<site>/site_config.json` bằng editor an toàn. **Giữ nguyên** `db_name`,
`db_password`, `db_user` (nếu có), `encryption_key` mà Bench tạo; không chép đè cả file.
Cấp quyền file `chmod 600 sites/<site>/site_config.json`. Không đưa secret vào
Vue/VITE_* vì chúng sẽ xuất hiện trong browser bundle.

- `joymedia_planner`: endpoint tương thích chat-completions để lập kế hoạch.
- `joymedia_vision`: endpoint phân tích hình ảnh; tên model phải đúng service đang chạy.
- `joymedia_translator`, `joymedia_writer`: endpoint riêng nếu có; fallback lần lượt
  về planner và translator theo `services/runtime/endpoints.py`.
- `comfyui_base_url`: URL ComfyUI từ máy chạy worker, không phải từ trình duyệt.
- `comfyui_input_dir`: thư mục input trên máy ComfyUI.
- `comfyui_api_key`: khóa Comfy.org nếu workflow sử dụng partner API; điền riêng
  vào cấu hình máy chủ khi cần. Gói không cung cấp tài khoản hay khóa dịch vụ.

Các cổng loopback trong mẫu giả định các dịch vụ cùng máy hoặc có SSH tunnel.
Nếu chạy container, dùng địa chỉ truy cập được từ container worker. Không công khai
MariaDB, Redis, ComfyUI hay endpoint model ra Internet mà thiếu lớp kiểm soát truy cập.
Các file trong `deploy/` là công cụ/template; cần chỉnh user, đường dẫn, host, model
và tài nguyên GPU theo hạ tầng bên nhận. Không chạy hàng loạt script deploy trên máy mới.

Từ thư mục Bench, khai báo worker rồi tái tạo Procfile:

```sh
bench set-config -g workers '{"joymedia_render":{"timeout":10800},"joymedia_planning":{"timeout":10800}}' --parse
bench setup procfile
python - <<'PYPROC'
from pathlib import Path
p = Path("Procfile")
text = p.read_text()
assert "worker_joymedia_planning:" in text, "Regenerate Procfile after setting workers"
if "worker_joymedia_planning_2:" not in text:
    p.write_text(text.rstrip() + "\nworker_joymedia_planning_2: bench worker --queue joymedia_planning\n")
PYPROC
bench --site joymedia-demo.localhost enable-scheduler
bench --site joymedia-demo.localhost execute joymedia.install.setup
```

Kiểm tra Procfile có worker mặc định phục vụ `short,default,long`, worker
`joymedia_render` và **2 process** `joymedia_planning`. Dừng rồi chạy lại `bench start` để nhận cấu hình mới.
`joymedia.install.setup` đăng ký workflow/pipeline và trả danh sách `todo` còn thiếu;
không cài ComfyUI, custom nodes hay weights. Đọc graph/model contracts trong
`joymedia/workflow_adapters/graphs/` và các lockfile/NOTICE trong `deploy/`.
Chỉ sau khi đã kiểm tra một lượt render với dịch vụ/model tương thích mới chọn pipeline:

```sh
bench --site joymedia-demo.localhost execute joymedia.install.setup --kwargs '{"promote": 1}'
bench doctor
```

Snapshot giữ workflow/pipeline lịch sử để mô tả đúng các video đã dựng; không tự
promote pipeline hay phục hồi job. Khi cần render lại, chọn pipeline phù hợp hạ tầng
hiện tại trong Video Settings và duyệt lại storyboard. Việc xem MP4 cũ không chứng minh
rằng model/custom nodes hiện tại có thể tái tạo video đó.

## 5. Kiểm tra, lỗi thường gặp và production

```sh
python apps/joymedia/scripts/verify_app_layout.py
cd apps/joymedia/joymedia/frontend
node --test tests/*.test.mjs
npm run build
cd ../../../..
# Chỉ trên site test riêng, không dùng database production:
bench --site joymedia-test.localhost set-config allow_tests 1 --parse
python apps/joymedia/scripts/run_tests.py joymedia-test.localhost
```

- Trang trắng/template missing: chạy lại build frontend, `bench build`, clear-cache.
- Không có DocType: kiểm tra `install-app joymedia`, chạy migrate và xem log lỗi.
- Job đứng: kiểm tra scheduler, Redis, đúng tên queue, worker và `bench doctor`.
- Endpoint not configured: điền cấu hình server, xác nhận endpoint từ máy worker.
- Sai mật khẩu DB: sửa thông tin kết nối trên site; không dùng cấu hình máy cũ.
- Lỗi thiếu model/node: cài đúng dependency của workflow trên ComfyUI rồi smoke-test.

`bench start` dành cho phát triển/demo. Production cần reverse proxy HTTPS,
process manager, quyền truy cập, backup database + public/private files + khóa mã hóa
lưu riêng, và thử restore trên máy khác. Không chuyển production bằng ZIP mã nguồn.
Trước nâng cấp: backup, dừng/hoàn tất job đang chạy, cập nhật source/dependencies,
migrate, build, restart services và smoke-test đăng nhập/dự án/render/export.
