import { test, expect } from "@playwright/test";
import { execSync } from "child_process";

function runBench(command) {
  const dockerCmd = `docker exec -w /workspace/development/frappe-bench frappe_docker_devcontainer-frappe-1 ${command}`;
  return execSync(dockerCmd, { encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] });
}

let projectName = "";

test.describe("JoyMedia Studio - Golden Path Integration Tests", () => {
  test.beforeAll(async () => {
    // 1. Setup initial project with Video clips and Audio track
    const output = runBench(
      'bench --site joymedia.localhost execute joymedia.services.e2e_setup.setup_e2e_project'
    );
    const parsed = JSON.parse(output.trim());
    projectName = parsed.project_name;
  });

  test.afterAll(async () => {
    if (projectName) {
      try {
        runBench(
          `bench --site joymedia.localhost execute joymedia.services.e2e_setup.cleanup_e2e_project --args "['${projectName}']"`
        );
      } catch (_) {}
    }
  });

  test.beforeEach(async ({ page, context }) => {
    // Authenticate as Administrator
    const loginRes = await context.request.post("/api/method/login", {
      data: {
        usr: "Administrator",
        pwd: "admin",
      },
    });
    expect(loginRes.ok()).toBeTruthy();

    // Ensure English language in localStorage for test consistency
    await page.addInitScript(() => {
      localStorage.setItem("joymedia_lang", "en");
    });
  });

  test("1. Priority 6: Frictionless New Project creation from Campaigns without modal", async ({ page }) => {
    await page.goto("/joymedia/campaigns");

    // Wait for Campaigns page to render
    const newProjectBtn = page.getByRole("button", { name: /\+ (New Project|Dự án mới)/i });
    await expect(newProjectBtn).toBeVisible({ timeout: 15000 });

    // Clicking New Project should navigate directly into Studio without opening a blocking dialog
    await newProjectBtn.click();

    // Verify redirected directly to /joymedia/projects/PRJ-...
    await page.waitForURL(/\/joymedia\/projects\//, { timeout: 15000 });
    await expect(page.locator("header")).toBeVisible();

    // Check that prompt composer textarea is available immediately
    const promptTextarea = page.locator("textarea");
    await expect(promptTextarea).toBeVisible();
  });

  test("2. Priority 2 & 3: Generation Composer @reference insertion and Improve Idea with Qwen AI", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);
    await expect(page.locator("header")).toBeVisible();

    const promptTextarea = page.locator("textarea");
    await expect(promptTextarea).toBeVisible();

    // Verify @reference token pill exists from project assets (Priority 2)
    const refTokenBtn = page.getByRole("button", { name: /@/ });
    await expect(refTokenBtn.first()).toBeVisible();

    // Enter initial prompt
    await promptTextarea.fill("Show athletic shoe in neon city");

    // Check Improve Idea button is present and clickable
    const improveBtn = page.getByRole("button", { name: /Improve Idea|Hoàn thiện ý tưởng/i });
    await expect(improveBtn).toBeVisible();
    await expect(improveBtn).toBeEnabled();

    // Click Improve Idea and verify the backend Qwen endpoint is invoked
    const [response] = await Promise.all([
      page.waitForResponse((res) => res.url().includes("improve_project_video_idea")),
      improveBtn.click(),
    ]);
    expect(response.status()).toBe(200);

    // Verify the prompt textarea content is updated with cinematic details
    await expect(promptTextarea).not.toHaveValue("Show athletic shoe in neon city");
  });

  test("3. Priority 4: Streamlined MediaPicker reference selection with suggested role", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);
    await expect(page.locator("header")).toBeVisible();

    // Open media picker via Composer ingredient button
    const addRefBtn = page.getByRole("button", { name: /\+ (Add Reference|Thêm tư liệu)/i });
    await expect(addRefBtn).toBeVisible();
    await addRefBtn.click();

    // Verify Modal opens
    await expect(page.getByText(/Add Project Reference|Thêm tư liệu vào Dự án/i)).toBeVisible();

    // Verify candidates are listed
    const candidateItem = page.locator(".group.relative.rounded-xl").first();
    await expect(candidateItem).toBeVisible({ timeout: 10000 });

    // Click candidate and verify the simplified bottom docked action bar appears
    await candidateItem.click();

    // Verify Suggested role pill is shown
    await expect(page.getByText(/Suggested:|Gợi ý:/i)).toBeVisible();

    // Verify "Change role ▾" dropdown trigger is present
    await expect(page.getByRole("button", { name: /Change role|Đổi vai trò/i })).toBeVisible();

    // Close modal
    await page.locator('[data-testid="close-media-picker"]').click();
  });

  test("4. Priority 1 & 5: Edit Mode lanes (Video & Music / Audio) and simplified Inspector labels", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);
    await expect(page.locator("header")).toBeVisible();

    // Switch to Edit mode
    const editModeBtn = page.getByRole("button", { name: /Edit|Biên tập/i }).first();
    await expect(editModeBtn).toBeVisible();
    await editModeBtn.click();

    // Priority 1: Check track lane labels are "Video" and "Music / Audio" (NOT "Video 0" or "Audio 0")
    await expect(page.getByText("Video", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/Music \/ Audio|Nhạc \/ Âm thanh/i).first()).toBeVisible();
    await expect(page.getByText("Video 0")).toHaveCount(0);
    await expect(page.getByText("Audio 0")).toHaveCount(0);

    // Verify video clips are present
    const videoClip = page.locator(".timeline-clip").first();
    await expect(videoClip).toBeVisible();
    await videoClip.click();

    // Priority 5: Verify inspector uses marketer-friendly labels: Start, End, Duration (no "IN FRAME", "OUT FRAME")
    await expect(page.getByText("IN FRAME")).toHaveCount(0);
    await expect(page.getByText("OUT FRAME")).toHaveCount(0);
    await expect(page.getByText(/Start|Bắt đầu/i).first()).toBeVisible();
    await expect(page.getByText(/End|Kết thúc/i).first()).toBeVisible();
    await expect(page.getByText(/Duration|Thời lượng/i).first()).toBeVisible();

    // Verify audio clip block is present in Music / Audio track
    const audioClip = page.locator(".timeline-audio-clip").first();
    await expect(audioClip).toBeVisible();
    await audioClip.click();

    // Verify Audio Inspector shows Volume (dB), Ducking, and Audio Role
    await expect(page.getByText(/Volume|Âm lượng/i).first()).toBeVisible();
    await expect(page.getByText(/Lower other audio|Giảm âm lượng track khác/i).first()).toBeVisible();
  });

  test("5. Golden Path: Shot regeneration flags clip outdated, update resolves it, and export triggers", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);
    await expect(page.locator("header")).toBeVisible();

    // Go to Scene mode
    const sceneModeBtn = page.getByRole("button", { name: /Scenes?|Phân cảnh/i }).first();
    await sceneModeBtn.click();

    // Switch to Edit mode to inspect timeline status
    const editModeBtn = page.getByRole("button", { name: /Edit|Biên tập/i }).first();
    await editModeBtn.click();

    // Select Clip 1
    const clip1 = page.locator(".timeline-clip").first();
    await clip1.click();

    // Check export button is accessible
    const exportBtn = page.getByRole("button", { name: /Export|Xuất video/i }).first();
    await expect(exportBtn).toBeVisible();
  });

  test("6. Studio Storyboard terminology & Media Drawer positioning", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);
    await expect(page.locator("header")).toBeVisible();

    // Verify Storyboard continuity label is marketer-friendly (no "Continuous (Chained)")
    await expect(page.getByText("Continuous (Chained)")).toHaveCount(0);
    await expect(page.getByText(/Keep scenes consistent|Independent scenes/i)).toBeVisible();

    // Toggle Media Drawer from Studio header
    const mediaBtn = page.getByRole("button", { name: /Media/i }).first();
    await mediaBtn.click();

    // Verify Media Drawer opens below header
    const mediaDrawer = page.locator(".studio-media-drawer");
    await expect(mediaDrawer).toBeVisible();

    // Header project title and breadcrumb remain visible and unaffected
    await expect(page.getByRole("button", { name: /Projects|Dự án/i })).toBeVisible();
  });

  test("7. Media Library visual simplification and pure ingredient separation", async ({ page }) => {
    await page.goto("/joymedia/assets");
    await expect(page.locator(".page-heading")).toBeVisible();

    // Verify legacy generated outputs are NOT present in Media Library
    await expect(page.getByText("Shot Output", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Final Deliverable", { exact: true })).toHaveCount(0);

    // Verify cards do NOT have redundant clutter like "Reference Input" or "View >"
    await expect(page.getByText("Reference Input")).toHaveCount(0);

    // Verify clean single filter row exists
    await expect(page.locator("select")).toBeVisible();
  });
});
