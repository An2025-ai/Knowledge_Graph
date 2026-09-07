# Brand Atlas Local UI

React + TypeScript + Vite interface for the local API.

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

Keep `VITE_API_TOKEN` equal to the backend `BRAND_ATLAS_TOKEN` while running
the local development server. The production desktop shell will inject a
random sidecar token instead.
