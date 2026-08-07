# Autonomous Futures Overview

Read-only React + TypeScript + Vite dashboard for the verified dataset foundation.

## Local development

From this directory:

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 4173
```

The Vite proxy expects the read-only FastAPI data API at `http://127.0.0.1:8000`.

## Quality checks

```bash
npm test -- --run
npm run lint
npm run build
```

The page consumes only:

- `GET /health`
- `GET /api/v1/dataset/bundle`
- `GET /api/v1/dataset/components`

Non-2xx API responses are shown as an explicit verification error. The UI does not fabricate metrics and does not expose account, position, order, or execution controls.
