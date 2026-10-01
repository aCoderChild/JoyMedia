import { test, expect } from "@playwright/test";
import { execSync } from "child_process";

let projectName = "";

test.describe("JoyMedia Studio - Revision & Edit Timeline Integration", () => {
  test.beforeAll(async () => {
    // 1. Setup initial project with Spec v1 and 2 clips
    const output = execSync(
      'bench --site joymedia.localhost execute joymedia.services.e2e_setup.setup_e2e_project',
      { encoding: "utf-8" }
    );
    const parsed = JSON.parse(output.trim());
    projectName = parsed.project_name;
  });

  test.afterAll(async () => {
    if (projectName) {
      try {
        execSync(
          `bench --site joymedia.localhost execute joymedia.services.e2e_setup.cleanup_e2e_project --args "['${projectName}']"`,
          { encoding: "utf-8" }
        );
      } catch (e) {
        // ignore cleanup error
      }
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
  });

  test("1. Edit mode available, can select Clip 2", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);

    // Wait for the studio page to load
    await expect(page.locator("header")).toBeVisible();

    // Switch to Edit mode
    const editModeBtn = page.getByRole("button", { name: "Edit", exact: true });
    await expect(editModeBtn).toBeVisible();
    await editModeBtn.click();

    // Verify timeline clips are visible
    const clip2 = page.locator(".timeline-clip").nth(1);
    await expect(clip2).toBeVisible();

    // Click Clip 2
    await clip2.click();

    // Verify Clip 2 is selected in the inspector
    await expect(page.getByText("Clip 2").first()).toBeVisible();
  });

  test("2. Trim Clip, reload page, trim persists", async ({ page }) => {
    await page.goto(`/joymedia/projects/${projectName}`);

    // Switch to Edit mode
    const editModeBtn = page.getByRole("button", { name: "Edit", exact: true });
    await editModeBtn.click();

    // Select Clip 1
    const clip1 = page.locator(".timeline-clip").first();
    await expect(clip1).toBeVisible();
    await clip1.click();

    const clipName = await clip1.getAttribute("data-clip-name");

    // Perform trim via backend execution
    execSync(
      `bench --site joymedia.localhost execute joymedia.services.timeline_editor.trim_timeline_clip --args "['${projectName}', '${clipName}', 10, 80]"`,
      { encoding: "utf-8" }
    );

    // Reload page
    await page.reload();
    const editBtn = page.getByRole("button", { name: "Edit", exact: true });
    await expect(editBtn).toBeVisible();
    await editBtn.click();

    // Inspect Clip 1: check IN FRAME = 10, OUT FRAME = 80 in inspector
    await page.locator(".timeline-clip").first().click();
    await expect(page.getByText("IN FRAME").locator("..")).toContainText("10");
    await expect(page.getByText("OUT FRAME").locator("..")).toContainText("80");
  });

});
