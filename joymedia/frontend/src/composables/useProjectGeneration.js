import { computed, ref, unref } from "vue";
import { call, toast } from "frappe-ui";

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

  function getFrappeErrorMessage(err, fallback = "Failed to start video generation.") {
    const data = err?.response?.data || err || {};

    if (Array.isArray(data.messages) && data.messages.length) {
      return data.messages
        .map((item) => item?.message || item)
        .filter(Boolean)
        .join("\n");
    }

    for (const raw of [data._server_messages, err?._server_messages]) {
      if (!raw) continue;
      try {
        const outer = typeof raw === "string" ? JSON.parse(raw) : raw;
        for (const entry of Array.isArray(outer) ? outer : [outer]) {
          try {
            const parsed = typeof entry === "string" ? JSON.parse(entry) : entry;
            if (parsed?.message) return parsed.message;
          } catch (_) {
            if (typeof entry === "string" && entry.trim()) return entry;
          }
        }
      } catch (_) {}
    }

    return data.exception || data.message || err?.message || fallback;
  }

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
          toast({ title: "Generation complete", text: "All video scenes are ready!", type: "success" });
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
        toast({ title: "Generation sync", text: syncError.value, type: "error" });
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
          await call("frappe.client.set_value", {
            doctype: "Media Project",
            name: project(),
            fieldname: "video_idea",
            value: videoIdeaPrompt.value.trim(),
          });
        } catch (_) {}
      }

      const res = await call("joymedia.joymedia.doctype.media_project.media_project.generate_project_video", {
        project_name: project(),
      });
      currentRun.value = { name: res?.run, status: res?.status || "Queued" };
      startPolling();
      if (onRefresh) await onRefresh();
      toast({ title: "Generation started", text: "Creating storyboard and rendering scenes...", type: "success" });
    } catch (err) {
      isGenerating.value = false;
      productionError.value = getFrappeErrorMessage(err);
      toast({ title: "Generation error", text: productionError.value, type: "error" });
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
      toast({ title: "Retrying", text: "Retrying generation for failed scenes.", type: "success" });
    } catch (err) {
      isGenerating.value = false;
      productionError.value = getFrappeErrorMessage(err, "Unable to retry.");
      toast({ title: "Retry failed", text: productionError.value, type: "error" });
    }
  }

  function handleGenerationRetry() {
    if (currentRun.value?.status === "Failed") {
      return retryFailedScenes();
    }
    return generateVideo();
  }

  async function reviseStoryboard() {
    isRevising.value = true;
    try {
      await call("joymedia.joymedia.doctype.media_project.media_project.revise_project_storyboard", {
        project_name: project(),
        use_current_workflow_defaults: true,
      });
      if (onRefresh) await onRefresh();
      toast({ title: "Storyboard revised", text: "AI updated the storyboard scenes.", type: "success" });
    } catch (err) {
      toast({ title: "Error", text: err?.message || "Failed to revise storyboard.", type: "error" });
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
        toast({ title: "Shot revised", text: "AI updated the shot prompt.", type: "success" });
      }
    } catch (err) {
      toast({ title: "AI revision failed", text: err?.message || "Could not revise shot.", type: "error" });
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
      toast({
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
          await call("frappe.client.set_value", {
            doctype: "Media Project",
            name: project(),
            fieldname: "video_idea",
            value: res.improved_idea,
          });
        } catch (_) {}
        toast({
          title: "Idea elevated ✨",
          text: "Qwen enhanced your concept with cinematic directions and ingredient references.",
          type: "success",
        });
        return res.improved_idea;
      }
    } catch (err) {
      toast({
        title: "AI idea improvement",
        text: err?.message || "Could not reach Qwen planner.",
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
    if (!run.final_asset_version && Number(run.completed_tasks || 0) === Number(run.total_tasks || 0)) {
      return "composing";
    }
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
    handleGenerationRetry,
    reviseStoryboard,
    reviseShotWithAi,
    improveVideoIdea,
    stopPolling,
  };
}
