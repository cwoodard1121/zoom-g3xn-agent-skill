import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the UI with hot reload and passes /api to the daemon
// (g3xn-daemon, or g3xn-daemon --sim for a virtual pedal).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8370", ws: true, changeOrigin: true },
    },
  },
});
