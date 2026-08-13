# RootLens screenshot guide

No screenshot image is committed yet. Capture the files below only from a clean local demo with representative synthetic data, then add repository-relative image links to the root README after each referenced file actually exists.

Use a consistent wide desktop viewport, keep text readable, and avoid covering key content with menus or browser chrome. Diagnosis Detail is the hero screenshot and should receive the strongest composition.

## Required captures

### 1. `overview.png`

Show the RootLens magnifying-glass and root-system logo, sidebar, **Incident Intelligence** heading, Diagnosis Service health, incident/diagnosis/explanation totals, recent activity, root-cause distribution, and telemetry coverage.

### 2. `incident-detail.png`

Show the incident case file, total request count, successful and failed outcomes, captured request/trace identifiers, and the **Run Diagnosis** area. Do not show hidden ground truth or a local file path.

### 3. `diagnosis-detail.png` — hero

Show the RootLens logo and sidebar, detected root cause, affected service, confidence and level, telemetry coverage, candidate scores, and the beginning of normalized evidence. Include supporting evidence in the viewport where possible. Favor this image as the first README screenshot because it communicates the core technical contribution.

### 4. `explanation-detail.png`

Show the explanation headline, executive summary, deterministic basis, provider and provider status, confidence, telemetry coverage, and validation or evidence-grounded sections. Template provider output is sufficient and avoids a network dependency.

### 5. `grafana.png`

Show meaningful RootLens metrics or structured logs. Prefer **RootLens Distributed Services Overview**, **RootLens Distributed Service Logs**, or a focused Explore view correlated by a synthetic request ID.

### 6. `jaeger.png`

Show one distributed trace involving Order, Inventory, and PostgreSQL spans where possible. Use a trace from synthetic demo traffic and expand enough detail to make the cross-service path clear.

### 7. `ci.png` — optional

Show GitHub Actions with the Python 3.12, Frontend Node 22, and Configuration validation jobs green. Crop account navigation and unrelated repository activity when practical.

## Privacy and release review

Never show:

- `.env` contents or API keys;
- browser account information or personal email;
- unrelated browser tabs when avoidable;
- private absolute filesystem paths;
- database, Grafana, or other credentials;
- live provider response IDs or private account usage.

Before committing, inspect every image at full resolution, verify that it contains only synthetic project data, and confirm its exact lowercase filename under `docs/screenshots/`.
