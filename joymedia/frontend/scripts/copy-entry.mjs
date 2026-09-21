import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("../templates/pages", { recursive: true });
copyFileSync(
  "../public/frontend/index.html",
  "../templates/pages/_joymedia.html",
);
