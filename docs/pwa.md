# PWA (Install to Home Screen)

The frontend is a installable Progressive Web App: on Android/Chrome (and iOS/Safari via "Add to Home Screen"), users get an app icon, a splash screen, and a browser-chrome-free window — without a native rewrite or a store listing. Implemented via [`vite-plugin-pwa`](https://vite-pwa-org.netlify.app/), which generates the manifest and a Workbox service worker at build time.

## Files

| File | Responsibility |
|------|---------------|
| `frontend/vite.config.ts` | `VitePWA()` plugin config: manifest fields (name, icons, theme/background color, `display: "standalone"`) and the Workbox `runtimeCaching` rules |
| `frontend/index.html` | `theme-color` meta tag + `apple-touch-icon` link (iOS). The `<link rel="manifest">` and service-worker registration script are auto-injected by the plugin at build time — not present in source |
| `frontend/public/pwa-192.png`, `pwa-512.png` | App icons (incl. one `purpose: "maskable"` entry reusing the 512px PNG), rasterized from `public/icon.svg` |

## Caching policy

`/api/*` and `/thumbnails/*` are set to `NetworkOnly` in the Workbox config — the service worker never serves cached document data or search results. Only the built app shell (JS/CSS/HTML) is precached, so the UI opens instantly offline but always shows live data once a request succeeds. There is no offline document viewing.

## Build output

`npm run build` (from `frontend/`) emits `dist/manifest.webmanifest`, `dist/sw.js`, and `dist/workbox-*.js` alongside the normal Vite bundle; `frontend/Dockerfile` ships these as static files, same as `index.html`.

## Requirements for install prompts

Android's install prompt (and iOS's "Add to Home Screen") requires HTTPS (or `localhost`). The k3s deployment already serves over HTTPS via cert-manager (see [deployment.md](deployment.md)), so no extra config is needed there; local `npm run dev` also qualifies since `localhost` is treated as a secure context.

## Verifying locally

`npm run dev` does **not** register the service worker (Workbox `devOptions` is left at its default, disabled). To see the real manifest/service-worker behavior, build and preview the production bundle:

```bash
cd frontend
npm run build
npm run preview
```
