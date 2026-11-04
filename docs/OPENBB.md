# OpenBB feasibility and implementation status — 2026-11-03

Feasible route: an authenticated, read-only FastAPI custom backend over SQLite, with documented Workspace metadata. **Nothing OpenBB-related is deployed or installed in this phase.** Authentication/HTTPS and endpoint implementation remain pending the validated collection pipeline.

## Architecture verified against official documentation

The current OpenBB Python documentation is version 5 and calls the Python stack Open Data Platform (ODP). `openbb-platform-api` supplies `openbb-api`, which can serve a FastAPI app and generate Workspace integration metadata. We should pin and test a specific supported release when implementing, rather than use old Terminal instructions or depend on a development branch. A custom backend does not require building a FYERS provider plugin just to display our stored analytics. Source: [official openbb-api documentation](https://docs.openbb.co/odp/python/extensions/interface/openbb-api).

Workspace documents custom REST backends using `widgets.json`, and optional `apps.json` layouts. The backend owns its data collection and calculation; Workspace consumes the endpoint results. Use the documented JSON specifications or supported metadata generation, never a Workspace fork. Backend access can use configured authentication headers. Browser CORS origins and network reachability must be tested against the selected Workspace deployment. Sources: [data integration](https://docs.openbb.co/workspace/developers/data-integration), [widgets.json](https://docs.openbb.co/workspace/developers/json-specs/widgets-json-reference), [apps.json](https://docs.openbb.co/workspace/developers/json-specs/apps-json-reference), [authentication FAQ](https://docs.openbb.co/workspace/getting-started/faqs).

The official pricing page currently lists Community as free for an individual and hosted by OpenBB; Lite at $2,400/year for a small team and self-hosted; Pro at custom pricing with self-hosted options. Workspace core is proprietary; ODP is a separate open-source product. These listings do not establish this user's entitlement, deployment package availability or VPS suitability. Confirm access and license terms before selecting Workspace hosting. Source: [official pricing and edition comparison](https://openbb.co/pricing/).

No assumption of built-in FYERS integration is made. FYERS remains an independently authenticated upstream collector, with its own account permissions and data-use requirements. The feasibility work has not tested a real Workspace account or actual FYERS responses.

## Planned read-only contract

| Proposed GET endpoint | SQLite-backed result |
|---|---|
| `/api/v1/spot` | NIFTY spot, observation/exchange time and quality |
| `/api/v1/futures` | Identified contract, completed bars, VWAP and OI |
| `/api/v1/walls` | CE/PE walls, fixed-strike migration and expiry |
| `/api/v1/checks` | Eighteen directional statuses, evidence, original score and vetoes |
| `/api/v1/gex` | Explicit scenario GEX/VEX/CEX units, assumptions and flip |
| `/api/v1/snapshots` | Paginated time/expiry/symbol-filtered history |
| `/api/v1/ml` | `NOT_TRAINED` until validated; later versioned research-only model outputs |
| `/health` | Minimal liveness; authenticated readiness/integrity separately |
| `/widgets.json`, `/apps.json` | Documented integration metadata and optional layout |

These are design contracts, not existing routes. Each result must expose `available_at`, quality and timestamp provenance. Never return a prior signal as current after an API error. No POST trading webhook or order-placement endpoint is planned. OpenBB/widgets are consumers, never scheduler triggers.

Security plan: backend bound to loopback under an unprivileged systemd account; separate read-only SQLite connection using URI `mode=ro` and query-only mode; bounded queries; HTTPS reverse proxy with a valid certificate; authenticated terminal session; separate backend authorization header for Workspace; credentials stored outside Git; restricted CORS; no secret-bearing query strings. A domain and chosen access policy will be required at deployment. None is configured yet.

Fallback if licensed Workspace access or compatible hosting is unavailable: a small responsive read-only HTML terminal using the same REST contract, with tables/charts and visible quality timestamps. It can run on the VPS behind the same authentication/HTTPS controls and Android browser. Retain compatible widget metadata for future Workspace use. No frontend has been built during this data-pipeline phase.
