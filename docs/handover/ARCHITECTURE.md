# Kiến trúc và sơ đồ

Sơ đồ được đối chiếu với `hooks.py`, `api/`, `services/`, Vue router và các DocType
trong bản nguồn bàn giao. Mermaid hiển thị được trên GitHub, GitLab hoặc VS Code
có hỗ trợ Mermaid. Các liên kết dưới đây là quan hệ ứng dụng/Frappe Link;
không khẳng định mọi quan hệ được tạo thành foreign key vật lý trong MariaDB.

## Thành phần triển khai

```mermaid
flowchart LR
    Browser["Browser: Vue 3 / Frappe UI"] --> Proxy["Reverse proxy HTTPS (production)"]
    Proxy --> Web["Frappe Web: Python / HTTP API"]
    Proxy --> Socket["Socket.IO realtime"]
    Web --> DB[("MariaDB: DocTypes + metadata")]
    Web --> Files["Site files: public / private"]
    Web --> Redis[("Redis cache + job queue")]
    Redis --> Workers["RQ workers: short/default, long, joymedia_planning, joymedia_render"]
    Scheduler["Frappe scheduler"] --> Redis
    Workers --> DB
    Workers --> Files
    Workers --> Models["Planner / Writer / Translator / Vision endpoints"]
    Workers --> Comfy["ComfyUI + custom nodes + GPU models"]
    Workers --> FFmpeg["FFmpeg: compose, audio, export"]
    Redis --> Socket
    Socket --> Browser
```

Frontend không giữ secret hay gọi thẳng MariaDB. Frappe xác thực session/CSRF,
kiểm tra quyền ở API và document level. Tác vụ dài chạy trong queue; scheduler
đồng bộ trạng thái ComfyUI và tiến trình batch. Metadata ở MariaDB, bytes của
media ở filesystem site; lưu database đơn lẻ không đủ để phục hồi media.

## Cấu trúc source và trách nhiệm

| Vị trí | Chức năng |
| --- | --- |
| `joymedia/frontend/src` | Trang Projects/ProjectStudio/Assets, component, composable, state và CSS |
| `joymedia/api` | Các thao tác dự án, asset, storyboard và creative batch |
| `joymedia/services/intake`, `planning`, `scene` | Nhập tài liệu, tham chiếu, kịch bản, contract của cảnh |
| `joymedia/services/keyframes`, `generation`, `workflows` | Chuẩn bị keyframe, run/task/attempt, điều phối và kết nối ComfyUI |
| `joymedia/services/editing`, `audio`, `review`, `consistency` | Timeline, âm thanh, xuất video, kiểm tra và duyệt |
| `joymedia/services/project`, `runtime` | Phiên bản dự án, realtime, endpoint và transaction |
| `joymedia/joymedia/doctype` | Schema JSON và controller dữ liệu Frappe |
| `joymedia/patches`, `patches.txt` bên trong package | Lịch sử migration; giữ nguyên khi bàn giao |
| `joymedia/workflow_adapters/graphs` | Hợp đồng và graph workflow versioned |
| `joymedia/vendor`, `fonts` | Mã/font vendored và giấy phép cần giữ |
| `deploy`, `scripts` | Công cụ vận hành, kiểm tra, đóng gói |
| `joymedia/demo`, `database` | JSON chuẩn, loader và SQL dữ liệu mẫu |

Hai thư mục `joymedia` lồng nhau là app package và module Frappe, không phải rác.
`apps/frappe`, `apps/joymedia` trong máy phát triển là thành phần của Bench;
không đưa toàn bộ runtime Bench vào app ZIP.

## Mô hình dữ liệu chính

```mermaid
erDiagram
    MEDIA_PROJECT ||--o{ SHOT : contains
    MEDIA_PROJECT ||--o{ PROJECT_REFERENCE : references
    MEDIA_PROJECT ||--o{ GENERATION_RUN : freezes
    MEDIA_PROJECT ||--o{ TIMELINE_CLIP : edits
    MEDIA_PROJECT ||--o{ MEDIA_PROJECT : versions
    MEDIA_ASSET ||--o{ ASSET_VERSION : versions
    ASSET_VERSION ||--o{ PROJECT_REFERENCE : selected_as
    SHOT ||--o{ SHOT_REFERENCE : references
    ASSET_VERSION ||--o{ SHOT_REFERENCE : selected_as
    GENERATION_PIPELINE ||--o{ GENERATION_PIPELINE_STEP : contains
    GENERATION_WORKFLOW ||--o{ GENERATION_PIPELINE_STEP : executes
    GENERATION_WORKFLOW ||--o{ GENERATION_RUN : configures
    GENERATION_RUN ||--o{ GENERATION_TASK : contains
    SHOT ||--o{ GENERATION_TASK : renders
    GENERATION_TASK ||--o{ GENERATION_ATTEMPT : retries
    GENERATION_ATTEMPT ||--o{ GENERATION_ARTIFACT : outputs
    ASSET_VERSION ||--o{ TIMELINE_CLIP : supplies
    SHOT ||--o{ REVIEW_COMMENT : receives
    ASSET_VERSION ||--o{ REVIEW_COMMENT : anchors
```

Đây là ERD rút gọn. Schema đầy đủ, kiểu trường, required/default, permission và
các child table khác nằm trong JSON từng DocType. Child table Frappe dùng
`parent`, `parenttype`, `parentfield`; không tự thay bằng một schema SQL khác.
Asset Version lưu phiên bản media, Generation Artifact lưu bằng chứng/output
của attempt; một lần retry không xóa lịch sử lần chạy trước.

## Luồng từ ý tưởng đến video

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant UI as Vue
    participant API as Frappe API
    participant DB as MariaDB
    participant Q as Queue / workers
    participant AI as Models / ComfyUI
    User->>UI: Tạo dự án, thêm ảnh hoặc workbook
    UI->>API: Lưu brief và tham chiếu
    API->>DB: Media Project / Asset Version
    API->>Q: Yêu cầu lập storyboard
    Q->>AI: Phân tích và lập kế hoạch
    Q->>DB: Lưu Shot / trạng thái
    User->>UI: Xem và duyệt storyboard
    UI->>API: Yêu cầu generation
    API->>DB: Freeze Run / Task / input versions
    API->>Q: Enqueue generation
    Q->>AI: Submit workflow
    AI-->>Q: Output / trạng thái
    Q->>DB: Attempt / Artifact / kết quả kiểm tra
    Q-->>UI: Realtime hoặc polling
    User->>UI: Chọn take, chỉnh timeline
    UI->>API: Export
    API->>Q: FFmpeg compose / audio / finishing
    Q->>DB: Asset Version + export status
    User->>UI: Review bản xuất và quyết định release
```

Export hoàn tất không đồng nghĩa video đã đạt mọi tiêu chí review/release.
Tình huống thiếu model, tham chiếu hoặc bằng chứng có thể cần người dùng xử lý.
Dữ liệu bàn giao có ba video đã dựng cùng storyboard/timeline/media. Loader khôi phục
snapshot để xem và chỉnh sửa; không khởi chạy lại chuỗi AI hoặc lịch sử job này.
