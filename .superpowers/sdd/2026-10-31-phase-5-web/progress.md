# Phase 5 web front end: progress ledger

- 2026-10-31 Tasks 1, 2, 3, 3a, 4, 5 done (see git log on phase-5-web).
- Ruling: ag-ui-adk copies client run state into the ADK session; HealthAgent keeps only a
  sanitised `location` (security + live location).
- Ruling: the web path counts every model call against the monthly chat cap (ChatBudget plugin)
  and refuses a run past it with RUN_ERROR code BUDGET.
- Pins: next 16.4.2, react 19.3.0, typescript 5.9.3, @ag-ui/client 1.0.3, tailwindcss 4.3.3,
  vitest 4.1.12, vite 7.3.7, @vitejs/plugin-react 5.2.0, eslint 9.39.5 (10 breaks
  eslint-config-next's plugins), playwright 1.64.1, axe 4.14.0, ag-ui-adk 0.11.0.
  npm uses legacy-peer-deps (arborist bug on jsdom's optional canvas peer); all versions exact.
- Task 6 owner pick: **A · Race telemetry** (dark-first, slanted condensed numbers, sector
  colours). Mockups: apps/web/design/directions.html; artifact
  https://claude.ai/artifact/6TeXwNvNaT6szubTzwfncY
