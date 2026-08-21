import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

function normalizedBase(value: string): string {
  const stripped = value.replace(/^\/+|\/+$/g, '');
  return stripped ? `/${stripped}/` : '/';
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const base = normalizedBase(env.VITE_APP_BASE_PATH || '/bcman/');
  const prefix = base.slice(0, -1);
  return {
    base,
    plugins: [
      react(),
      {
        name: 'redirect-app-base',
        configureServer(server) {
          server.middlewares.use((req, res, next) => {
            if (req.url === prefix) {
              res.writeHead(302, { Location: base });
              res.end();
              return;
            }
            next();
          });
        },
      },
    ],
    server: {
      proxy: {
        [`${prefix}/api`]: { target: 'http://localhost:8000', changeOrigin: true },
      },
    },
  };
});
