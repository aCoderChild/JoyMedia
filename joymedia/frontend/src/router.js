import { createRouter, createWebHistory } from "vue-router";
import Campaigns from "./pages/Campaigns.vue";
import ProjectStudio from "./pages/ProjectStudio.vue";
import Assets from "./pages/Assets.vue";
import { useSession } from "./stores/session";

const router = createRouter({
  history: createWebHistory("/joymedia"),
  routes: [
    { path: "/", redirect: "/projects" },
    { path: "/campaigns", redirect: "/projects" },
    { path: "/projects", component: Campaigns },
    { path: "/projects/:name", component: ProjectStudio },
    { path: "/assets", redirect: "/library" },
    { path: "/library", component: Assets },
    { path: "/:pathMatch(.*)*", redirect: "/projects" },
  ],
});

router.beforeEach((to) => {
  const { isLoggedIn, refreshSession } = useSession();
  refreshSession();
  if (!isLoggedIn.value) {
    const portalPath = `/joymedia${to.fullPath}`;
    window.location.href = `/login?redirect-to=${encodeURIComponent(portalPath)}`;
    return false;
  }
});

export default router;
