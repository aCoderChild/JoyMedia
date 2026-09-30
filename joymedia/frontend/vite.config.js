import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "/assets/joymedia/frontend/",
  plugins: [vue()],
  build: {
    outDir: "../public/frontend",
    emptyOutDir: true,
  },
});
