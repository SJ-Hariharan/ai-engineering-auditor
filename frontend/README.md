# AI Engineering Auditor - frontend

Next.js (App Router) + TypeScript (strict) + Tailwind CSS v4 + shadcn/ui (Base UI flavour) + lucide-react. No other runtime dependencies.

## Develop

```bash
cp .env.example .env.local   # optional; defaults to http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
npm run build && npm start   # production
npx tsc --noEmit && npm run lint
```

The backend must be running (see `../backend`). The browser only talks to same-origin `/api/*`;
`next.config.ts` rewrites that to `AUDITOR_API_URL` (default `http://localhost:8000`), which keeps the
`auditor_session` cookie first-party. `AUDITOR_API_URL` is read when the server starts / builds.

## Structure

```
src/lib/types.ts            API types, mirrors docs/API.md
src/lib/api.ts              the only API client: credentials, X-Auditor-Client header, ApiError, 401 -> /login
src/lib/format.ts           labels, dates, link helpers
src/hooks/use-api.ts        useResource (fetch + optional polling) and useAction
src/app/(auth)/             /login, /register
src/app/(app)/              /, /projects/[id], /audits/[id] (auth-gated layout with header)
src/components/app/         shared UI: badges, score, DiffView, CodeView, EmptyState, dropzone, ...
src/components/report/      audit report: one file per tab + finding sheet + dependency graph (hand-rolled SVG)
src/components/ui/          shadcn/ui primitives
```

Deep links: `/audits/{id}?tab=code&file=path/to/file.py&line=21`. Tabs: overview, findings, architecture, quality, testing, code, learn, remediation, methodology.
