# Frontend toolchain audit exception

- Owner: `@zaizhudepeiqi` (repository owner/maintainer)
- Reviewed: 2026-07-17
- Expires: 2026-08-31

## Scope

The full `npm audit` report for the locked frontend dependency graph currently contains 55 vulnerabilities: 10 low, 27 moderate, 17 high, and 1 critical. The affected paths are rooted in the Umi development and build toolchain, including `@umijs/max`, Umi bundler packages, webpack tooling, and `dva-immer`. Representative advisory identifiers include `GHSA-33f9-j839-rf8h` for the critical `immer` advisory reached through `dva-immer`, plus `GHSA-9jgg-88mc-972h` and `GHSA-4v9v-hfq4-rm2v` in `webpack-dev-server` paths.

This exception does not assert that every advisory is unexploitable. It permits only the full toolchain audit report in the [CI workflow](../../.github/workflows/ci.yml) to be non-blocking while the Umi dependency roots are remediated. The locked production dependency audit, `npm --prefix frontend audit --omit=dev --audit-level=high`, remains blocking and currently reports 1 moderate, 0 high, and 0 critical vulnerabilities. The locked backend audit also remains blocking.

## Exposure and controls

The frontend has no production Node server. Deployment uses the statically generated browser bundle, so the Umi development server and build-time packages are not shipped as a long-running production service. The local development command binds to the loopback host `127.0.0.1`. The application Mock/request-record server and source have been removed, but `mockjs@1.1.0` remains transitively through `@umijs/max-plugin-openapi@2.0.3` and `@umijs/openapi@1.14.1`. Its high-severity prototype-pollution path is assessed as build-time generator exposure processing the trusted, checked-in [OpenAPI schema](../api/openapi.json), not as a shipped server or runtime dependency. This assessment reduces the exposed surface; it does not claim exploitation is impossible.

Compensating controls are:

- exact frontend dependency resolution in [package-lock.json](../../frontend/package-lock.json) and exact package versions in [package.json](../../frontend/package.json);
- blocking production-only frontend and locked backend audits in CI;
- an exact Node.js 24.16.0 and npm 11.13.0 toolchain;
- SHA-pinned CI actions: `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5`, `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065`, `astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78`, and `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`;
- a loopback-only development server and no production exposure of the development server;
- repository quality, documentation, secret, and Compose configuration checks on each pull request and push to `main`.

## Remediation and triggers

`@zaizhudepeiqi`, as repository owner/maintainer, will remove the exception as soon as compatible Umi/build dependency updates clear the high and critical findings. CI blocks after the expiry date. Reassessment is required before the expiry date and immediately if a production dependency reaches high or critical severity, a toolchain advisory becomes reachable in the generated browser bundle or CI inputs, the development server becomes network-accessible, Mock or request-record capability is reintroduced, the checked-in schema becomes untrusted input, or the frontend architecture adds a production Node server. Any such trigger makes the full audit blocking until the exposure is reviewed and remediated.
