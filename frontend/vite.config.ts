import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    target: "es2020",
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three", "@react-three/fiber", "@react-three/postprocessing", "postprocessing"],
          vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query", "framer-motion"],
        },
      },
    },
  },
  test: { environment: "jsdom", globals: false },
} as never);
