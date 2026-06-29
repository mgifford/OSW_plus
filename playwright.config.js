import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
  },
  webServer: {
    command: "mkdir -p _site/api _site/data && cp -r public/. _site/ && cp -r api/. _site/api/ && cp data/places_with_coords.csv _site/data/ && python3 scripts/generate_knowledge_site.py --year 2025 --out _site && python3 scripts/generate_knowledge_site.py --year 2026 --out _site && npx serve _site --listen 3000 --no-clipboard",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
  },
});
