import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built bundle lands in app/web, which FastAPI serves. One service, one
// deployable — which is what keeps hosting inside the budget.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../app/web",
    emptyOutDir: true,
  },
  server: {
    // In development the API runs separately; proxying keeps cookies
    // same-origin so sessions behave exactly as they will in production.
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
