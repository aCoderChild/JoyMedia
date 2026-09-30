import frappeUIPreset, { content as frappeUIContent } from "frappe-ui/tailwind";
import colors from "tailwindcss/colors";

/** @type {import('tailwindcss').Config} */
export default {
  presets: [frappeUIPreset],
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
    ...frappeUIContent,
  ],
  theme: {
    extend: {
      colors: {
        indigo: colors.indigo,
        emerald: colors.emerald,
        zinc: colors.zinc,
        slate: colors.slate,
        amber: colors.amber,
        surface: {
          base: "var(--surface-base)",
          card: "var(--surface-card)",
          hover: "var(--surface-hover)",
          active: "var(--surface-active)",
          muted: "var(--surface-muted)",
        },
        outline: {
          border: "var(--outline-border)",
          subtle: "var(--outline-subtle)",
        },
        ink: {
          primary: "var(--ink-primary)",
          secondary: "var(--ink-secondary)",
          muted: "var(--ink-muted)",
        },
        primary: {
          accent: "var(--primary-accent)",
          "accent-hover": "var(--primary-accent-hover)",
        },
      },
    },
  },
  plugins: [],
};
