import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/bcman/',
  plugins: [
    react(),
    {
      name: 'redirect-bcman',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/bcman') {
            res.writeHead(302, { Location: '/bcman/' });
            res.end();
            return;
          }
          next();
        });
      },
    },
  ],
  server: { proxy: { '/bcman/api': { target: 'http://localhost:8000', changeOrigin: true } } },
});