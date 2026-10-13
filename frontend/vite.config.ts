import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend URL for the dev-server proxy: agent-server on localhost when run on
// the host, the docker service name when the frontend container runs in
// docker-compose (set BACKEND_URL=http://agent-server:8000 there).
const backend = process.env.BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/oauth": { target: backend, changeOrigin: true },
      // AG-UI event stream endpoint used by the chat page (POST /stream/{user_id}).
      "/stream": { target: backend, changeOrigin: true },
    },
  },
});
