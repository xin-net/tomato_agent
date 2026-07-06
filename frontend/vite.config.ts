import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          const normalized = id.replace(/\\/g, '/');
          if (normalized.includes('/antd/es/')) {
            const component = normalized.split('/antd/es/')[1]?.split('/')[0] || 'core';
            return `antd-${component}`;
          }
          if (normalized.includes('/rc-') || normalized.includes('/@rc-component/')) {
            const match = normalized.match(/node_modules\/(?:@rc-component\/([^/]+)|([^/]+))/);
            return `vendor-rc-${match?.[1] || match?.[2] || 'misc'}`;
          }
          if (normalized.includes('/@ant-design/cssinjs')) return 'vendor-antd-cssinjs';
          if (normalized.includes('/@ant-design/')) return 'vendor-antd-infra';
          if (id.includes('@xyflow/react')) return 'vendor-flow';
          if (id.includes('@ant-design/icons')) return 'vendor-icons';
          if (id.includes('antd')) return 'vendor-antd-core';
          if (id.includes('react') || id.includes('react-dom')) return 'vendor-react';
          if (id.includes('dayjs')) return 'vendor-dayjs';
          return 'vendor-misc';
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
});
