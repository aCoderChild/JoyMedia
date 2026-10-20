import { createRouter, createWebHistory } from "vue-router";
import Projects from "./pages/Projects.vue";
import ProjectStudio from "./pages/ProjectStudio.vue";
import Assets from "./pages/Assets.vue";
import { useSession } from "./stores/session";

const router = createRouter({
  history: createWebHistory("/joymedia"),
  routes: [
    { path: "/", redirect: "/projects" },
    { path: "/campaigns", redirect: "/projects" },
    { path: "/projects", component: Projects },
    { path: "/projects/:name", component: ProjectStudio },
    { path: "/assets", redirect: "/library" },
    { path: "/library", component: Assets },
    { path: "/:pathMatch(.*)*", redirect: "/projects" },
  ],
});

router.beforeEach(async (to) => {
  const { isLoggedIn, refreshSession, refreshAccess } = useSession();
  refreshSession();
  if (!isLoggedIn.value) {
    const portalPath = `/joymedia${to.fullPath}`;
    window.location.href = `/login?redirect-to=${encodeURIComponent(portalPath)}`;
    return false;
  }
  const access=await refreshAccess(to.params.name || null);
  if(access.role==='unassigned' && to.path!=='/projects') return '/projects';
  if(to.path==='/library' && !access.can_use_library) return '/projects';
  if(to.query.editor && !access.can_use_advanced_editor) { const query={...to.query};delete query.editor;return {path:to.path,query}; }
  if(access.reviewer && (to.path==='/library' || to.query.editor || (to.params.name && !access.can_open_project))) return '/projects';
});

export default router;
