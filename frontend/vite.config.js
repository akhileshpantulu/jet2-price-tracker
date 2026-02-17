import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // For GitHub Pages: set to '/<repo-name>/' for production builds
  // Change 'jet2-price-tracker' to your actual GitHub repo name
  base: command === 'serve' ? '/' : '/jet2-price-tracker/',
}))
