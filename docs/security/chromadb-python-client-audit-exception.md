# ChromaDB Python client audit exception

- Owner: `@zaizhudepeiqi` (repository owner/maintainer)
- Reviewed: 2026-07-17
- Expires: 2026-08-31

## Advisory

The locked backend dependency `chromadb==1.5.9` is affected by `PYSEC-2026-311`, also identified as `CVE-2026-45829` and `GHSA-f4j7-r4q5-qw2c`, with a CVSS score of 9.3. The [authoritative OSV record](https://osv.dev/vulnerability/PYSEC-2026-311) lists versions 1.0.0 through 1.5.9 as affected and currently lists no fixed version.

Exploitation requires running Chroma's Python FastAPI server and submitting a malicious model repository with `trust_remote_code` behavior through the collection endpoint. This repository's backend carries `chromadb` only as a client-side dependency. The current [Chroma adapter](../../backend/app/infrastructure/vector/chroma.py) uses `httpx` for an outbound heartbeat and never launches the affected Chroma Python server. The independent development [Chroma container](../../deploy/compose/compose.deps.yml) publishes its port only on loopback.

These boundaries reduce exposure to the reported server-side path, but they do not make the dependency zero risk. The affected package remains in the locked environment, the independent Chroma service still processes requests, and future application or deployment changes could invalidate this assessment.

## Controls

- CI exports production requirements from the frozen backend lock and ignores only `PYSEC-2026-311`; every other `pip-audit` finding remains blocking.
- CI fails after 2026-08-31 unless this exception and its narrow ignore are removed or explicitly reviewed again.
- Application code does not launch Chroma's Python FastAPI server or enable model repository loading through a collection endpoint.
- Development Chroma access is bound to `127.0.0.1`, and the application uses a fixed outbound health endpoint.
- Dependency versions, container images, CI actions, Python, and uv are exactly locked or pinned.

## Remediation and triggers

`@zaizhudepeiqi` will update `chromadb`, refresh the backend lock, and remove the ignore as soon as OSV identifies a fixed compatible release. Immediate reassessment is required if the backend starts a Chroma Python server, imports server components, accepts untrusted model repositories or `trust_remote_code` configuration through collection operations, exposes Chroma beyond loopback, changes the independent Chroma deployment, or receives materially revised advisory guidance. Any trigger makes this exception invalid until the exposure is reviewed and remediated.
