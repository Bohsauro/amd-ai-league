import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // bind su 0.0.0.0: raggiungibile da LAN e Tailscale (no solo localhost)
    port: 3000,
    strictPort: false,
  },
});
