# CI/CD tạm thời trên máy chủ GPU

## Phạm vi

Trong giai đoạn chưa có Cloud Hosting, cùng một máy GPU chạy Frappe, MariaDB,
Redis, worker, planner/vision và ComfyUI. Code và dữ liệu Frappe phải nằm trên
ổ bền vững; không đặt database, `sites/`, model hoặc private files trong Git.
Máy chủ cần có tên miền HTTPS, reverse proxy và đăng nhập riêng cho từng khách
hàng. Chỉ cổng HTTPS ra Internet; không công khai MariaDB, Redis hoặc ComfyUI.

Workflow [`deploy-gpu.yml`](../.github/workflows/deploy-gpu.yml) chỉ chạy thủ
công từ nhánh `main`, sau khi đúng commit đó có CI thành công. GitHub Environment
`gpu-production` phải giới hạn nhánh `main` và có người duyệt trước khi cấp
secrets. Các pull request không được dùng khóa deploy. Không bật tự động deploy
trên mỗi push khi sản phẩm còn dùng chung GPU với người dùng thử.

## Chuẩn bị một lần trên máy chủ

1. Cài Bench/Frappe production với Supervisor hoặc systemd, Nginx/HTTPS,
   MariaDB, Redis, Node và `ffmpeg`. Dùng user riêng sở hữu Bench; không chạy
   pipeline dưới `root`. `apps/joymedia` phải là Git checkout riêng của repo,
   không phải symlink trỏ vào thư mục Bench. Cài app và dịch vụ GPU theo
   [hướng dẫn vận hành](operations.md). Kiểm tra web, bốn worker, scheduler và
   ComfyUI trước lần deploy CI/CD đầu.
2. Tạo ổ sao lưu ngoài thư mục Bench, đủ chứa database cùng toàn bộ public và
   private files. Mẫu cấu hình: [`gpu-deploy.env.example`](../deploy/gpu-deploy.env.example).
   Đặt bản thực tại `/etc/joymedia/deploy.env`, quyền `0640`, root sở hữu và
   nhóm của user deploy được đọc. `HEALTH_URL` là URL nội bộ có route `/joymedia`.
   `BACKUP_ROOT` phải tồn tại; mặc định cần ít nhất 20 GiB trống. Đồng bộ bản
   sao lưu sang máy/ổ độc lập, vì bản trên chính GPU không bảo vệ khi ổ hỏng.
3. Tạo SSH key riêng cho user deploy. Trong GitHub Environment đặt secrets
   `GPU_DEPLOY_TARGET` (`user@host`), `GPU_DEPLOY_SSH_KEY`, và
   `GPU_SSH_KNOWN_HOSTS` (host key đã xác minh trực tiếp với quản trị viên);
   tùy chọn variable `GPU_DEPLOY_PORT`. Không lấy host key ngay trong workflow.
   Giới hạn key này cho đúng máy, đúng user, không cho sudo không cần thiết.
4. Trên máy GPU, checkout `apps/joymedia` cần quyền đọc repo để `git fetch`
   commit đã qua CI. Nên dùng deploy key **read-only** riêng. Giữ cấu hình
   Frappe/ComfyUI, token model và khóa API trong site config hoặc secret store.

## Mỗi lần phát hành

| Bước | Tự động kiểm tra/thực hiện | Kết quả cần có |
| --- | --- | --- |
| CI | Lint, Frappe tests, build Vue | CI của đúng commit xanh |
| Chốt phát hành | Duyệt `gpu-production`, khóa deploy, kiểm tra checkout sạch và commit thuộc `main` | Không phát hành từ PR hoặc mã chưa kiểm tra |
| Giữ an toàn dữ liệu | Kiểm tra hàng đợi; bật maintenance, dừng scheduler, kiểm tra lại rồi backup database, site config, public và private files | Thư mục backup riêng cho commit, các tệp nhất quán |
| Nâng cấp | Cài dependencies, build Vue/Bench, `bench migrate`, `bench restart` | Schema và frontend khớp cùng commit |
| Smoke test | Worker online, ComfyUI sống, web `/joymedia` phản hồi; sau đó khôi phục trạng thái scheduler ban đầu | Mới mở lại người dùng |

Các job GPU có thể kéo dài: chọn cửa sổ phát hành khi hàng đợi trống. Script
kiểm tra cả Generation Run/Attempt và job Frappe còn chờ hoặc đang chạy. Nếu
còn job, pipeline dừng **trước** khi sửa code. Không ép hủy một render đang chạy.
Do backup tệp riêng có thể lớn, đo thời gian backup thật trên máy GPU rồi đặt
cửa sổ bảo trì phù hợp. Workflow có giới hạn 60 phút; tăng sau khi đo nếu cần.

## Khi phát hành lỗi

Nếu lỗi trước khi đổi code, script trả lại maintenance/scheduler. Nếu lỗi sau
khi đổi code, site **giữ maintenance mode** và scheduler tắt, đồng thời in đường
dẫn backup và commit cũ. Không chỉ `git checkout` mã cũ sau `bench migrate`:
schema đã có thể thay đổi. Quản trị viên xác định bước lỗi, phục hồi snapshot
database và tệp bằng `bench --site <site> restore <database.sql.gz>
--with-public-files <files.tgz> --with-private-files <private-files.tgz>` khi
cần, rồi checkout commit cũ, cài/build lại dependencies, migrate và restart.
Thử restore trên site thử trước khi nhận khách hàng; lưu cả `site_config` và
khóa mã hóa backup. Chỉ tắt maintenance và bật lại scheduler sau smoke test.

## Chuyển sang Cloud Hosting

Giữ cùng commit, CI và quy tắc kiểm tra. Tạo môi trường deploy mới (ví dụ
`cloud-production`) với secrets và cấu hình host riêng; không tái dùng SSH key
GPU. Chuyển database, `sites/` và private files bằng bản backup đã thử restore;
chuyển planner/vision/ComfyUI thành endpoint nội bộ qua kết nối bảo mật.
Kiểm tra quyền khách hàng, job queue, first frame, video và backup trên cloud
trước khi đổi DNS. Sau chuyển đổi, máy GPU chỉ phục vụ AI; khóa deploy web
GPU cũ và giữ backup để quay lui trong thời gian chuyển tiếp.

CI/CD này xác nhận hạ tầng và ứng dụng khởi động được. Nó không tự chứng nhận
chất lượng hình ảnh hay logic video; bản demo vẫn cần bộ kiểm tra nội dung và
an toàn đầu ra riêng trước khi mở generation cho khách hàng.
