import { createRouter, createWebHistory } from "vue-router";
import Campaigns from "./pages/Campaigns.vue";
import CampaignDetail from "./pages/CampaignDetail.vue";
import Assets from "./pages/Assets.vue";
import Reviews from "./pages/Reviews.vue";
import NewCampaign from "./pages/NewCampaign.vue";
import Onboarding from "./pages/Onboarding.vue";
import { useSession } from "./stores/session";

export default createRouter({
  history: createWebHistory("/joymedia"),
  routes: [
    { path: "/", redirect: "/campaigns" },
    { path: "/campaigns", component: Campaigns },
    { path: "/campaigns/new", component: NewCampaign },
    { path: "/campaigns/:name", component: CampaignDetail },
    { path: "/assets", component: Assets },
    { path: "/reviews", component: Reviews },
    { path: "/onboarding", component: Onboarding },
  ],
});

router.beforeEach((to) => {
  const { isLoggedIn } = useSession();
  if (!isLoggedIn.value) {
    window.location.href = `/login?redirect-to=${encodeURIComponent(to.fullPath)}`;
    return false;
  }
});
