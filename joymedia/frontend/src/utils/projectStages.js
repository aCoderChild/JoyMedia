// The pipeline as the client sees it, built only from what Frappe already saved.
// Nothing here estimates: a count, a percentage or a time appears only when the
// underlying record actually carries it.

const STATE_ORDER = { attention: 0, running: 1, review: 2, waiting: 3, done: 4 };

function pick(lang, en, vi) {
  return lang === "vi" ? vi : en;
}

/**
 * @returns {{key:string,label:string,state:'done'|'running'|'review'|'waiting'|'attention',
 *   detail:string, reason?:string, percent?:number, etaMinutes?:number}[]}
 */
export function buildStages({ project = {}, production = null, automatic = null, shots = [], assets = [], frames = [], lang = "vi" } = {}) {
  const t = (en, vi) => pick(lang, en, vi);
  const stages = [];

  // 1. Script — the scenes themselves are the evidence it is done.
  const sceneCount = shots.length;
  if (!sceneCount && automatic?.status === "Needs Attention") {
    stages.push({ key: "script", label: t("Preparation", "Chuẩn bị video"), state: "attention",
      detail: t("The automatic process stopped. See the reason below.", "Quá trình tự động đã dừng. Xem lý do bên dưới.") });
  } else if (!sceneCount && ["Queued", "Planning", "Locations"].includes(automatic?.status)) {
    stages.push({ key: "script", label: t("Preparation", "Chuẩn bị video"), state: automatic.status === "Queued" ? "waiting" : "running",
      detail: automatic.status === "Queued" ? t("Waiting for the system.", "Đang chờ hệ thống xử lý.") : t("Preparing the script and references.", "Đang chuẩn bị kịch bản và tư liệu.") });
  } else if (project.planning_status === "Failed") {
    stages.push({
      key: "script", label: t("Script", "Kịch bản"), state: "attention",
      detail: t("Preparing the scenes stopped.", "Việc chuẩn bị cảnh đã dừng."),
      reason: project.planning_error || "",
    });
  } else if (project.planning_status === "Running") {
    stages.push({
      key: "script", label: t("Script", "Kịch bản"), state: "running",
      detail: sceneCount
        ? t(`${sceneCount} scenes so far.`, `Đã có ${sceneCount} cảnh.`)
        : t("Being prepared.", "Đang chuẩn bị."),
    });
  } else if (sceneCount) {
    stages.push({
      key: "script", label: t("Script", "Kịch bản"), state: "done",
      detail: t(`${sceneCount} scenes prepared.`, `Đã chuẩn bị ${sceneCount} cảnh.`),
    });
  } else {
    stages.push({
      key: "script", label: t("Script", "Kịch bản"), state: "waiting",
      detail: t("Waiting for your idea or storyboard.", "Đang chờ ý tưởng hoặc bảng phân cảnh."),
    });
  }

  // 2. References — report what is attached, by kind, without guessing readiness.
  const roleOf = (asset) => String(asset.reference_role || asset.display_category || asset.asset_category || "").toLowerCase();
  const products = assets.filter((asset) => roleOf(asset).includes("product")).length;
  const characters = assets.filter((asset) => /character|person/.test(roleOf(asset))).length;
  const referenceCount = assets.filter((asset) => asset.reference_key).length;
  stages.push({
    key: "references",
    label: t("Product and character references", "Tư liệu sản phẩm và nhân vật"),
    state: referenceCount ? "done" : "waiting",
    detail: referenceCount
      ? t(`${products} product, ${characters} character, ${referenceCount} in total.`,
          `${products} sản phẩm, ${characters} nhân vật, tổng ${referenceCount}.`)
      : t("Waiting for reference pictures.", "Đang chờ ảnh tư liệu."),
  });

  // 3. Storyboard — the approval record is the status.
  const approval = project.storyboard_approval_status || "Draft";
  const warnings = (project.storyboard_timing_warnings || []).length;
  stages.push({
    key: "storyboard",
    label: t("Storyboard", "Bảng phân cảnh"),
    state: !sceneCount ? "waiting" : approval === "Approved" ? "done" : approval === "Ready for Review" ? "review" : "running",
    detail: !sceneCount
      ? t("Waiting for the script.", "Đang chờ kịch bản.")
      : approval === "Approved"
        ? t("Approved.", "Đã duyệt.")
        : approval === "Ready for Review"
          ? t("Ready for your review.", "Sẵn sàng để bạn duyệt.")
          : t("Being written.", "Đang soạn."),
    reason: warnings
      ? t(`${warnings} timing warning(s) to check.`, `Có ${warnings} cảnh báo thời lượng cần xem.`)
      : "",
  });

  // 4. Scene images. A frame supplied from a storyboard panel is "authored": the
  // stage marks it done and the AI leaves it alone, so both kinds are counted
  // here. Counting only needs_keyframe would make supplied scenes disappear.
  // One row per scene: a supplied frame can still need a draw when the scene
  // composites a product, so the buckets overlap and must not be summed.
  const relevant = frames.filter((row) => row.needs_keyframe || row.authored_frame);
  const total = relevant.length;
  const ready = relevant.filter((row) => row.url && !row.stale).length;
  const authoredCount = relevant.filter((row) => row.authored_frame).length;
  const fromSheet = authoredCount
    ? t(` ${authoredCount} from your storyboard.`, ` ${authoredCount} lấy từ bảng phân cảnh.`)
    : "";
  stages.push({
    key: "images",
    label: t("Scene images", "Ảnh đầu cảnh"),
    state: !total ? "waiting" : ready >= total ? "done" : ready ? "running" : "waiting",
    detail: total
      ? t(`${ready} of ${total} ready.${fromSheet}`, `${ready}/${total} đã xong.${fromSheet}`)
      : t("Waiting for the storyboard.", "Đang chờ bảng phân cảnh."),
    reason: total && ready < total
      ? t(`${total - ready} still to draw.`, `Còn ${total - ready} cảnh cần vẽ.`)
      : "",
  });

  // 5. Video — the run carries its own progress, so only pass it through.
  if (production && production.status) {
    const failed = Number(production.failed_tasks || 0);
    const total = Number(production.total_tasks || 0);
    const done = Number(production.completed_tasks || 0);
    const running = production.status === "Queued" || production.status === "Running";
    const stage = {
      key: "video",
      label: t("Scene video", "Video từng cảnh"),
      state: failed ? "attention" : production.status === "Completed" ? "done" : running ? "running" : "waiting",
      detail: total
        ? t(`${done} of ${total} jobs done.`, `${done}/${total} phần việc đã xong.`)
        : t("Preparing.", "Đang chuẩn bị."),
      reason: production.error_summary || "",
    };
    // A percentage only once the run actually has jobs to measure against.
    if (total > 0 && Number.isFinite(Number(production.progress))) stage.percent = Math.round(Number(production.progress));
    if (running && Number.isFinite(Number(production.eta_minutes))) stage.etaMinutes = Number(production.eta_minutes);
    stages.push(stage);
  } else {
    stages.push({
      key: "video", label: t("Scene video", "Video từng cảnh"), state: "waiting",
      detail: t("Waiting for the scene images.", "Đang chờ ảnh đầu cảnh."),
    });
  }

  // 6. Finishing — the post-production record names its own step.
  const post = project.post_production_status || "Idle";
  stages.push({
    key: "finishing",
    label: t("Finishing the video", "Hoàn thiện video"),
    state: post === "Failed" ? "attention" : post === "Completed" ? "done" : post === "Running" || post === "Queued" ? "running" : "waiting",
    detail: project.post_production_step
      || (post === "Completed"
        ? t("Done.", "Đã xong.")
        : post === "Idle"
          ? t("Waiting for the scene videos.", "Đang chờ video từng cảnh.")
          : post),
    reason: project.post_production_error || "",
  });

  return stages;
}

/** The one line to show at the top: the most urgent stage, then the active one. */
export function currentStage(stages = []) {
  return [...stages].sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state])[0] || null;
}
