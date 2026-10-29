# Agent handoff

Private bundle of separate source snapshots, not a complete machine backup or integrated product.

## Clone

```sh
git clone https://github.com/femmynuppu/agent-handoff-2026-10-28.git
cd agent-handoff-2026-10-28
cat HANDOFF.md
cat INVENTORY.md
```

Read `INVENTORY.md` first. Then study each project's own README, docs, source, dependencies, and tests. OMP local change summary: `projects/oh-my-pi-telegram/LOCAL-CHANGES.md`.

## Limits

- Keep private; do not publish to a public repository or use this bundle as a security boundary.
- Credentials, host assistant configs, databases, local memory, client-market data, and operational logs were excluded.
- Autogenesis contains property-validation code only; no database or memory integration. Finance application code was excluded. Do not launch workers or other financial services from this repository.
- SIQE evidence/database and original dataset are excluded, so old empirical claims cannot be replayed.
- Prometheus contains source and public references only; its runtime OMP extension and private solutions/memory are excluded.
- The OMP Claude tracing tool, which had a checked-in private-key debug pair, was omitted from the source snapshot.
- No tests or runtime smoke commands were run for this bundle. Run only a scoped test after reviewing its fixture/data paths and effects.
