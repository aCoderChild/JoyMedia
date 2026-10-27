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
        rio: {
          50: '#ecfeff',
          100: '#cffafe',
          200: '#a5f3fc',
          300: '#67e8f9',
          400: '#22d3ee',
          500: '#0e7490',
          600: '#155e75',
          700: '#164e63',
          800: '#083344',
          900: '#082f49',
          950: '#061b2b',
        },
        emerald: colors.emerald,
        zinc: colors.zinc,
        slate: colors.slate,
        amber: colors.amber,
        rose: colors.rose,
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
