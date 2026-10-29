# Autogenesis: property-verification snapshot

This export deliberately includes only the standalone property-verification library, its direct test, and the matching skill.

## Run

```sh
cd projects/autogenesis
python3 tests/test_property_verifier.py
```

The original companion Memory Nexus used implicit paths to a machine-global MemPalace knowledge graph and Chroma database; its host-specific integration tests and benchmarks are not included. No memory databases or companion service are bundled. Never use someone else's assistant memory store. This is not the original “Cycle 3” full project, audit package or benchmark workspace; no such claims are being made for this subset.
