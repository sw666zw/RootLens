# RootLens v1.0.0 release checklist

Keep every item unchecked until a person verifies it for the final release candidate. The commands below do not replace manual product, screenshot, CI, or release review.

## Automated checks

- [ ] Full Python tests pass:

  ```bash
  python -m pytest \
    services/inventory/tests \
    services/order/tests \
    services/diagnosis/tests \
    tools/scenario_runner/tests \
    tools/diagnosis_engine/tests \
    tools/benchmark_runner/tests \
    -v
  ```

- [ ] Ruff check passes: `python -m ruff check services tools test_support`
- [ ] Ruff format check passes: `python -m ruff format --check services tools test_support`
- [ ] Frontend tests pass: `cd apps/web && npm run test:run`
- [ ] Frontend lint passes: `cd apps/web && npm run lint`
- [ ] Frontend format check passes: `cd apps/web && npm run format:check`
- [ ] TypeScript typecheck passes: `cd apps/web && npm run typecheck`
- [ ] Frontend production build passes: `cd apps/web && npm run build`
- [ ] Docker Compose configuration validates: `docker compose config`
- [ ] GitHub Actions Python, frontend, and configuration jobs are green on the final commit.

## Security and repository

- [ ] `.env` is ignored and not tracked.
- [ ] No real API key is tracked.
- [ ] Generated runtime artifacts are not tracked; only runtime `.gitkeep` files remain.
- [ ] `apps/web/node_modules` is not tracked.
- [ ] `apps/web/dist` is not tracked.
- [ ] Frontend coverage output is not tracked.
- [ ] Runtime benchmark JSON and Markdown reports are ignored.
- [ ] Curated examples contain no private filesystem paths, account details, or live provider identifiers.
- [ ] Obvious secret-pattern sanity check has been reviewed without exposing suspected values in logs or reports.

## Manual product review

- [ ] Overview reviewed fullscreen.
- [ ] Incidents list and Incident Detail reviewed.
- [ ] Diagnosis Detail reviewed.
- [ ] Explanation Detail reviewed.
- [ ] Mobile and responsive layouts sanity-checked.
- [ ] Wide-screen layout sanity-checked.
- [ ] Grafana opens and shows meaningful RootLens data.
- [ ] Jaeger opens and shows a distributed trace.
- [ ] Prometheus opens and all three application targets are up.
- [ ] Live `inventory-unavailable` incident demo completed.
- [ ] Benchmark completed if a final live result is desired.
- [ ] Product screenshots captured using [screenshots/README.md](screenshots/README.md).
- [ ] README screenshot links added only after the image files exist.
- [ ] Documentation links checked.
- [ ] Complete 3–5 minute demo walkthrough rehearsed.

## Release

- [ ] Final pull request merged.
- [ ] Local `main` pulled after merge.
- [ ] Annotated `v1.0.0` tag created from the verified release commit.
- [ ] `v1.0.0` tag pushed.
- [ ] GitHub Release created from `v1.0.0` with accurate notes and screenshots.
