import { computed, ref, unref } from "vue";
import { call } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";

export function useProjectGeneration(projectName, onRefresh) {
  const isGenerating = ref(false);
  const isRevising = ref(false);
  const aiRevisionLoading = ref(false);
  const productionError = ref("");
  const videoIdeaPrompt = ref("");
  const currentRun = ref(null);
  let pollTimeout = null;
  let polling = false;
  let consecutivePollFailures = 0;
  const syncError = ref("");

  const getFrappeErrorMessage = errorMessage;

  function project() {
    return unref(projectName);
  }

  function stopPolling() {
    polling = false;
    if (pollTimeout) {
      clearTimeout(pollTimeout);
      pollTimeout = null;
    }
  }

  async function pollRun() {
    if (!polling) return;
    try {
      const snap = await call(
        "joymedia.joymedia.doctype.media_project.media_project.refresh_project_studio",
        { name: project() }
      );
      consecutivePollFailures = 0;
      syncError.value = "";
      if (snap) {
        currentRun.value = snap.production || null;
      }
      if (snap?.production) {
        const status = currentRun.value.status;
        if (status === "Completed") {
          stopPolling();
          isGenerating.value = false;
          if (onRefresh) await onRefresh(snap);
          notify({ title: "Generation complete", text: "All scenes are ready. Adding transitions and the soundtrack…", type: "success" });
        } else if (status === "Failed") {
          stopPolling();
          isGenerating.value = false;
          productionError.value = currentRun.value.error_summary || "Generation encountered an issue.";
          if (onRefresh) await onRefresh(snap);
        } else {
          // Still generating
          if (onRefresh) await onRefresh(snap);
        }
      }
    } catch (err) {
      consecutivePollFailures += 1;
      if (consecutivePollFailures >= 3) {
        syncError.value = "Connection lost while checking generation. Generation may still be running.";
        notify({ title: "Generation sync", text: syncError.value, type: "error" });
      }
    } finally {
      if (polling && ["Queued", "Running"].includes(currentRun.value?.status)) {
        pollTimeout = setTimeout(pollRun, 3000);
      }
    }
  }

  function startPolling() {
    stopPolling();
    polling = true;
    pollRun();
  }

  function resumeProduction(production) {
    currentRun.value = production || null;
    const active = ["Queued", "Running"].includes(production?.status);
    isGenerating.value = active;
    if (active) {
      startPolling();
    } else {
      stopPolling();
    }
  }

  async function generateVideo() {
    if (isGenerating.value) return;
    isGenerating.value = true;
    productionError.value = "";
    try {
      // If there is an idea prompt, we can save it to the project before generating
      if (videoIdeaPrompt.value?.trim()) {
        try {
          await call("joymedia.joymedia.doctype.media_project.media_project.update_project_brief", {
            project_name: project(),
            video_idea: videoIdeaPrompt.value.trim(),
          });
        } catch (_) {}
      }

      const res = await call("joymedia.joymedia.doctype.media_project.media_project.generate_project_video", {
        project_name: project(),
      });
      currentRun.value = { name: res?.run, status: res?.status || "Queued" };
      startPolling();
      if (onRefresh) await onRefresh();
      notify({ title: "Generation started", text: "Creating storyboard and rendering scenes...", type: "success" });
    } catch (err) {
      isGenerating.value = false;
      productionError.value = getFrappeErrorMessage(err);
      notify({ title: "Generation error", text: productionError.value, type: "error" });
    }
  }

  async function appendScenes({ durationSeconds, instruction, continuity }) {
    if (isGenerating.value) return;
    isGenerating.value = true;
    try {
      const res = await call(
        "joymedia.joymedia.doctype.media_project.media_project.append_project_scenes",
        {
          project_name: project(),
          duration_seconds: durationSeconds,
          instruction: instruction || "",
          continuity: Boolean(continuity),
        }
      );
      currentRun.value = { name: res?.run, status: res?.status || "Queued" };
      startPolling();
      if (onRefresh) await onRefresh();
      return res;
    } catch (err) {
      isGenerating.value = false;
      throw err;
    }
  }

  async function retryFailedScenes() {
    try {
      isGenerating.value = true;
      productionError.value = "";
      await call("joymedia.joymedia.doctype.media_project.media_project.retry_project_failed_jobs", {
        project_name: project(),
      });
      startPolling();
      if (onRefresh) await onRefresh();
      notify({ title: "Retrying", text: "Retrying generation for failed scenes.", type: "success" });
    } catch (err) {
      isGenerating.value = false;
      productionError.value = getFrappeErrorMessage(err, "Unable to retry.");
      notify({ title: "Retry failed", text: productionError.value, type: "error" });
    }
  }

  async function cancelGeneration() {
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.cancel_project_generation", {
        project_name: project(),
      });
      stopPolling();
      isGenerating.value = false;
      currentRun.value = { ...(currentRun.value || {}), status: "Cancelled" };
      if (onRefresh) await onRefresh();
      notify({ title: "Generation stopped", text: "The video generation was stopped.", type: "success" });
    } catch (err) {
      notify({ title: "Unable to stop generation", text: errorMessage(err, "Please try again."), type: "error" });
    }
  }

  function handleGenerationRetry() {
    if (currentRun.value?.status === "Failed") {
      return retryFailedScenes();
    }
    return generateVideo();
  }

  async function reviseStoryboard(instruction = "") {
    isRevising.value = true;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.revise_project_storyboard", {
        project_name: project(),
        instruction,
        use_current_workflow_defaults: true,
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Storyboard revised", text: "AI updated the storyboard scenes.", type: "success" });
    } catch (err) {
      notify({ title: "Error", text: errorMessage(err, "Failed to revise storyboard."), type: "error" });
    } finally {
      isRevising.value = false;
    }
  }

  async function reviseShotWithAi(shotName, instruction) {
    if (!instruction?.trim() || aiRevisionLoading.value) return;
    aiRevisionLoading.value = true;
    try {
      const res = await call("joymedia.joymedia.doctype.media_project.media_project.revise_project_shot_with_ai", {
        project_name: project(),
        shot_name: shotName,
        instruction: instruction.trim(),
      });
      if (res?.generation_prompt || res?.prompt) {
        // Auto apply revision to shot
        await call("joymedia.joymedia.doctype.media_project.media_project.apply_project_shot_ai_revision", {
          project_name: project(),
          shot_name: shotName,
          values: res,
          regenerate: false,
        });
        if (onRefresh) await onRefresh();
        notify({ title: "Shot revised", text: "AI updated the shot prompt.", type: "success" });
      }
    } catch (err) {
      notify({ title: "AI revision failed", text: errorMessage(err, "Could not revise shot."), type: "error" });
    } finally {
      aiRevisionLoading.value = false;
    }
  }

  const improvingIdea = ref(false);

  async function improveVideoIdea(currentIdea) {
    const textToImprove = (currentIdea || videoIdeaPrompt.value || "").trim();
    if (!textToImprove || improvingIdea.value) return;
    improvingIdea.value = true;
    try {
      notify({
        title: "Qwen AI Creative Planner",
        text: "Analyzing product & ingredients to craft cinematic video concept...",
        type: "info",
      });
      const res = await call(
        "joymedia.services.ai_director.improve_project_video_idea",
        {
          project_name: project(),
          current_idea: textToImprove,
        }
      );
      if (res?.improved_idea) {
        videoIdeaPrompt.value = res.improved_idea;
        try {
          await call("joymedia.joymedia.doctype.media_project.media_project.update_project_brief", {
            project_name: project(),
            video_idea: res.improved_idea,
          });
        } catch (_) {}
        notify({
          title: "Idea elevated ✨",
          text: "Qwen enhanced your concept with cinematic directions and ingredient references.",
          type: "success",
        });
        return res.improved_idea;
      }
    } catch (err) {
      notify({
        title: "AI idea improvement",
        text: errorMessage(err, "Could not reach Qwen planner."),
        type: "error",
      });
    } finally {
      improvingIdea.value = false;
    }
  }

  const isProductionActive = computed(() => {
    return isGenerating.value || ["Queued", "Running"].includes(currentRun.value?.status);
  });

  const generationPhase = computed(() => {
    const run = currentRun.value;
    if (isGenerating.value && !run) return "starting";
    if (!run) return "idle";
    if (run.status === "Failed") return "failed";
    if (run.status === "Completed") return "completed";
    if (!run.total_tasks) return "planning";
    if (Number(run.completed_tasks || 0) < Number(run.total_tasks || 0)) return "rendering";
    return "running";
  });

  return {
    isGenerating,
    isRevising,
    aiRevisionLoading,
    improvingIdea,
    productionError,
    getFrappeErrorMessage,
    videoIdeaPrompt,
    currentRun,
    isProductionActive,
    generationPhase,
    syncError,
    resumeProduction,

    generateVideo,
    appendScenes,
    retryFailedScenes,
    cancelGeneration,
    handleGenerationRetry,
    reviseStoryboard,
    reviseShotWithAi,
    improveVideoIdea,
    stopPolling,
  };
}
