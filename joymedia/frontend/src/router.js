import { createRouter, createWebHistory } from "vue-router";
import Campaigns from "./pages/Campaigns.vue";
import CampaignDetail from "./pages/CampaignDetail.vue";
import Assets from "./pages/Assets.vue";
import Reviews from "./pages/Reviews.vue";

export default createRouter({
  history: createWebHistory("/joymedia"),
  routes: [
    { path: "/", redirect: "/campaigns" },
    { path: "/campaigns", component: Campaigns },
    { path: "/campaigns/:name", component: CampaignDetail },
    { path: "/assets", component: Assets },
    { path: "/reviews", component: Reviews },
  ],
});
