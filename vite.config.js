import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  base: command === "serve" ? "/" : "/burbank-police-incidents/",
  server: {
    port: 5173,
    strictPort: true,
  },
}));
