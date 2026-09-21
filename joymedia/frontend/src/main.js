import "frappe-ui/style.css";
import "./style.css";
import { createApp } from "vue";
import { FrappeUI, frappeRequest, setConfig } from "frappe-ui";
import App from "./App.vue";
import router from "./router";

setConfig("resourceFetcher", frappeRequest);

createApp(App).use(FrappeUI).use(router).mount("#app");
