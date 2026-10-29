# Inventory

Private point-in-time handoff; not a whole-machine backup or integrated application. Root-relative paths below identify the content in this checkout.

| Path | Source | Actual contents |
|---|---|---|
| `projects/autogenesis/` | `/home/qiin-ai/autogenesis`, no Git | Property-verification source, its standalone property test, and skill. The accompanying Memory Nexus, host-memory tests, personal-store benchmark and identity-bearing reports have been excluded. |
| `projects/autogenesis_finance/` | `/home/qiin-ai/autogenesis_finance` | README-only placeholder. The finance application is not included because it depends on private research data, machine-level integrations and credential-incident context. |
| `projects/siqe_quest/` | `/home/qiin-ai/siqe_quest`, HEAD `587e035` (`main`), no remote | Selected source/test/config/docs and Pine example, including local uncommitted work; no SQLite, source dataset, evidence, recovery backups, report snapshots or large generated reference engine. Historic research claims cannot be replayed here. |
| `projects/oh-my-pi-telegram/` | `/home/qiin-ai/omp-telegram-bridge`, paired with `oh-my-pi-bridge` | `feat/telegram-bridge` HEAD `1eee04c91497f756d77df20abd169b7c3896a88d` source archive plus local Telegram command and property-verifier skill. The reusable PEM/Claude trace helper and several test fixtures containing realistic credential-shaped strings are excluded from this exported source tree. |
| `projects/deep-research-skills/` | `/home/qiin-ai/deep-research-skills`, branch `master` | Clean project snapshot with license, README, skills, agents, tests and scripts. |
| `projects/prometheus/` | `/home/qiin-ai/prometheus`, no Git | Code, docs, tests not requiring an installed external Hermes source tree, curriculum and public source manifests. Private solutions, memory and host extension excluded; not a live plugin. |
| `projects/id-finance-mcp/` | `/home/qiin-ai/tools/id-finance-mcp` | `server.py` only; virtualenv excluded. |
| `projects/maverick-mcp/`, `projects/momentum-mcp/` | Third-party local checkouts | Clean committed archives with original licenses; copied source, not maintained forks. |
| `snippets/property-verifier/SKILL.md` | OMP source | Standalone verification skill. |
| `research/` | — | Empty. No personal market-analysis notes are included. |

## Explicit exclusions

- All `.git` directories/remotes in archived snapshots, `.env` values, assistant configs, GitHub/SSH credentials, chat/session logs, memory stores, provider tokens and home configuration.
- SQLite/database/WAL/SHM files, local client/source datasets, finance raw-webpage payloads, evaluation data, telemetry, reports tied to private datasets, machine service logs, virtualenvs, `node_modules`, caches, compiled objects, host-generated data and backups.
- Entire `/home/qiin-ai/autogenesis_finance/data/`, containing private research/client artifacts and runtime databases. Finance source was withheld as inseparable from that environment; only a safe empty placeholder remains.
- OMP's `claude-trace-cli.ts` and `scripts/claude-trace.ts` were excluded together due to a bundled private MITM key. Additional upstream tests/docs with long credential-shaped fixtures were removed; inspect upstream history before restoring those files.
- The finance data/client/DB tree and host operations are excluded. Its remaining project folder contains only a README placeholder, not source code.
- SIQE SQLite state, evidence, recovery backups, generated data, operational report artifacts and the portable experiment runner are excluded. No report dataset is included.
- Prometheus private task/answer references, local memory and host OMP/Hermes integrations are excluded.
