import { computed, ref, unref } from "vue";
import { call } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";

export function useProjectGeneration(projectName, onRefresh) {
  const isGenerating = ref(false);
  const isRevising = ref(false);
  const revisionError = ref("");
  const aiRevisionLoading = ref(false);
  const productionError = ref("");
  const videoIdeaPrompt = ref("");
  const isSavingIdea = ref(false);
  let lastSavedIdea = null;
  const currentRun = ref(null);
  let pollTimeout = null;
  let polling = false;
  let consecutivePollFailures = 0;
	let syncFailureNotified = false;
  const syncError = ref("");

  const getFrappeErrorMessage = errorMessage;

  function project() {
    return unref(projectName);
  }

  async function saveVideoIdea(currentIdea = videoIdeaPrompt.value) {
    const idea = String(currentIdea || "").trim();
    if (idea === lastSavedIdea || isSavingIdea.value) return true;
    isSavingIdea.value = true;
    try {
      await call("joymedia.api.projects.update_project_brief", {
        project_name: project(),
        video_idea: idea,
      });
      lastSavedIdea = idea;
      return true;
    } catch (err) {
      notify({
        title: "Video idea",
        text: errorMessage(err, "Unable to save your video idea."),
        type: "error",
      });
      return false;
    } finally {
      isSavingIdea.value = false;
    }
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
        "joymedia.api.projects.refresh_project_studio",
        { name: project() }
      );
      consecutivePollFailures = 0;
		 syncFailureNotified = false;
      syncError.value = "";
      if (snap) {
        const planning = snap.project?.planning_status;
        if (planning === "Failed" && currentRun.value?.planning) {
          stopPolling();
          isGenerating.value = false;
          productionError.value = snap.project.planning_error || "";
          currentRun.value = snap.production || null;
          if (onRefresh) await onRefresh(snap);
          notify({ title: "Storyboard", text: productionError.value, type: "error" });
          return;
        }
        currentRun.value = activeRun(snap.production, planning);
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
      } else if (snap) {
        // Planning may finish before a Generation Run exists. Apply the new
        // storyboard and release the busy state instead of leaving the UI
        // stuck on the last queued planning snapshot.
        if (onRefresh) await onRefresh(snap);
        if (!["Queued", "Running"].includes(currentRun.value?.status)) {
          stopPolling();
          isGenerating.value = false;
        }
      }
    } catch (err) {
      consecutivePollFailures += 1;
      if (consecutivePollFailures >= 3) {
		 syncError.value = "Generation status is temporarily unavailable. Generation may still be running.";
		 // A failed poll is recoverable. Show one actionable notice per outage,
		 // rather than adding a toast every three seconds until the API recovers.
		 if (!syncFailureNotified) {
			 notify({ title: "Generation sync", text: syncError.value, type: "error" });
			 syncFailureNotified = true;
		 }
      }
    } finally {
      if (polling && ["Queued", "Running"].includes(currentRun.value?.status)) {
		 const retryDelay = consecutivePollFailures ? Math.min(15000, 3000 * consecutivePollFailures) : 3000;
		 pollTimeout = setTimeout(pollRun, retryDelay);
      }
    }
  }

  function startPolling() {
    stopPolling();
    polling = true;
    pollRun();
  }

  // While the AI director plans the storyboard there is no run yet; the studio
  // shows it as a queued run so progress and polling carry on.
  function activeRun(production, planningStatus) {
    return planningStatus === "Running" ? { status: "Queued", planning: true, shots: [] } : production || null;
  }

  function resumeProduction(production, planningStatus = null) {
    currentRun.value = activeRun(production, planningStatus);
    production = currentRun.value;
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
      // Save the current creative brief before planning the storyboard.
      if (videoIdeaPrompt.value?.trim() && !(await saveVideoIdea())) {
        isGenerating.value = false;
        return;
      }

      const res = await call("joymedia.api.projects.generate_project_video", {
        project_name: project(),
      });
      currentRun.value = res?.status === "Planning"
        ? activeRun(null, "Running")
        : { name: res?.run, status: res?.status || "Queued" };
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
        "joymedia.api.storyboard.append_project_scenes",
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
      await call("joymedia.api.projects.retry_project_failed_jobs", {
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
      await call("joymedia.api.projects.cancel_project_generation", {
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
    const request = String(instruction || "").trim();
    if (!request) {
      revisionError.value = "Describe the storyboard change you want the AI to make.";
      notify({ title: "Storyboard revision", text: revisionError.value, type: "error" });
      return false;
    }
    isRevising.value = true;
    revisionError.value = "";
    try {
      await call("joymedia.api.storyboard.revise_project_storyboard", {
        project_name: project(),
        instruction: request,
        use_current_workflow_defaults: true,
      });
      if (onRefresh) await onRefresh();
      notify({ title: "Storyboard revised", text: "AI updated the scenes. Generate a new version to render them.", type: "success" });
      return true;
    } catch (err) {
      revisionError.value = errorMessage(err, "Failed to revise storyboard.");
      notify({ title: "Storyboard revision", text: revisionError.value, type: "error" });
      return false;
    } finally {
      isRevising.value = false;
    }
  }

  async function reviseShotWithAi(shotName, instruction) {
    if (!instruction?.trim() || aiRevisionLoading.value) return;
    aiRevisionLoading.value = true;
    try {
      const res = await call("joymedia.api.storyboard.revise_project_shot_with_ai", {
        project_name: project(),
        shot_name: shotName,
        instruction: instruction.trim(),
      });
      if (res?.generation_prompt || res?.prompt) {
        // Auto apply revision to shot
        await call("joymedia.api.storyboard.apply_project_shot_ai_revision", {
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
        title: "AI Creative Planner",
        text: "Analyzing product & ingredients to craft cinematic video concept...",
        type: "info",
      });
      const res = await call(
        "joymedia.services.planning.revisions.improve_project_video_idea",
        {
          project_name: project(),
          current_idea: textToImprove,
        }
      );
      if (res?.improved_idea) {
        videoIdeaPrompt.value = res.improved_idea;
        await saveVideoIdea(res.improved_idea);
        notify({
          title: "Idea elevated ✨",
          text: "AI enhanced your concept with cinematic directions and ingredient references.",
          type: "success",
        });
        return res.improved_idea;
      }
    } catch (err) {
      notify({
        title: "AI idea improvement",
        text: errorMessage(err, "Could not reach AI planner."),
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
    revisionError,
    aiRevisionLoading,
    improvingIdea,
    productionError,
    getFrappeErrorMessage,
    videoIdeaPrompt,
    isSavingIdea,
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
    saveVideoIdea,
    stopPolling,
  };
}
