import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production's own build (ADR 0069, ADR 0076): its screens, served by FastAPI
// under /production-app/ and shown inside HBA's frame at /production/. Kept
// apart from frontend/ so neither side's styles can reach the other.
export default defineConfig({
  base: "/production-app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "next/image": fileURLToPath(new URL("./src/shims/next-image.tsx", import.meta.url)),
      "next/navigation": fileURLToPath(new URL("./src/shims/next-navigation.ts", import.meta.url)),
    },
  },
  build: {
    outDir: "../app/web_production",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
