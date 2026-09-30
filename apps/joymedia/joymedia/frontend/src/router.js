import { createRouter, createWebHistory } from "vue-router";
import Campaigns from "./pages/Campaigns.vue";
import ProjectStudio from "./pages/ProjectStudio.vue";
import Assets from "./pages/Assets.vue";
import { useSession } from "./stores/session";

const router = createRouter({
  history: createWebHistory("/joymedia"),
  routes: [
    { path: "/", redirect: "/campaigns" },
    { path: "/campaigns", component: Campaigns },
    { path: "/projects/:name", component: ProjectStudio },
    { path: "/assets", component: Assets },
  ],
});

router.beforeEach((to) => {
  const { isLoggedIn } = useSession();
  if (!isLoggedIn.value) {
    const portalPath = `/joymedia${to.fullPath}`;
    window.location.href = `/login?redirect-to=${encodeURIComponent(portalPath)}`;
    return false;
  }
});

export default router;
