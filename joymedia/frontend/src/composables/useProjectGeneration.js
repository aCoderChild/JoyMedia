import { computed, ref, unref } from "vue";
import { call, toast } from "frappe-ui";

export function useProjectGeneration(projectName, onRefresh) {
  const isGenerating = ref(false);
  const isRevising = ref(false);
  const aiRevisionLoading = ref(false);
  const productionError = ref("");
  const videoIdeaPrompt = ref("");
  const currentRun = ref(null);
  let pollInterval = null;

  function project() {
    return unref(projectName);
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  async function pollRun() {
    try {
      const snap = await call(
        "joymedia.joymedia.doctype.media_project.media_project.get_project_workspace",
        { name: project() }
      );
      if (snap?.production) {
        currentRun.value = snap.production;
        const status = snap.production.status;
        if (status === "Completed") {
          stopPolling();
          isGenerating.value = false;
          if (onRefresh) await onRefresh();
          toast({ title: "Generation complete", text: "All video scenes are ready!", type: "success" });
        } else if (status === "Failed") {
          stopPolling();
          isGenerating.value = false;
          productionError.value = snap.production.error_summary || "Generation encountered an issue.";
          if (onRefresh) await onRefresh();
        } else {
          // Still generating
          if (onRefresh) await onRefresh();
        }
      }
    } catch (_) {
      // Keep polling or stop if error persists
    }
  }

  function startPolling() {
    stopPolling();
    pollInterval = setInterval(pollRun, 3000);
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
      productionError.value = err?.message || "Failed to start video generation.";
      toast({ title: "Generation error", text: productionError.value, type: "error" });
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
      toast({ title: "Retry failed", text: err?.message || "Unable to retry.", type: "error" });
    }
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

  return {
    isGenerating,
    isRevising,
    aiRevisionLoading,
    improvingIdea,
    productionError,
    videoIdeaPrompt,
    currentRun,
    isProductionActive,

    generateVideo,
    retryFailedScenes,
    reviseStoryboard,
    reviseShotWithAi,
    improveVideoIdea,
    stopPolling,
  };
}
