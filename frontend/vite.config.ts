import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    // `npm run dev` talks to the API of the running Docker stack (make up), like nginx does.
    proxy: { "/api": "http://localhost:8080" },
  },
});
