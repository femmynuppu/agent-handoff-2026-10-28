---
name: property-verifier
description: Mechanical Invariant Verification & High-Efficiency Streaming Engine for autonomous agent workflows. Enforces zero-drift Kahan summation, true spectral covariance/correlation matrix PSD & symmetry validation, stack-safe Kahn topological ordering with iterative cycle path pinpointing (>1,000 nodes), contract schema validation, and <2 MiB streaming record processing.
---

# Property Verifier & High-Efficiency Streaming Engine

A mechanical verification skill ensuring code execution correctness, mathematical invariants, and strict resource bounding for OMP and Hermes agent operations.

## Capabilities

### 1. Zero-Drift Kahan-Neumaier Compensated Summation
Eliminates floating point catastrophic cancellation on ill-conditioned series ($10^{16} + 1.0 - 10^{16}$ or small delta additions). Compensates running rounding error dynamically and guarantees consistent results across `add()` and batch `add_all()`:
```python
from autogenesis_property_verifier import KahanCompensatedSum

accumulator = KahanCompensatedSum()
total = accumulator.add_all(ill_conditioned_data)
print(f"Total: {total}, Error bound: {accumulator.error_bound()}")
```

### 2. Spectral Covariance & Correlation Invariant Validation
Verifies that generated statistical, financial, or machine learning matrices satisfy rigorous mathematical laws via exact spectral decomposition (NumPy `linalg.eigvalsh` with pure-Python Jacobi solver fallback):
- Square matrix dimension ($K \times K$)
- Symmetry: $Cov(i, j) = Cov(j, i)$
- True Positive Semi-Definiteness (PSD): $\lambda_{\min}(\Sigma) \ge -\text{tol}$ ($v^T \Sigma v \ge 0$ for all $v \in \mathbb{R}^K$)
- Variance non-negativity on diagonal: $Cov(i, i) \ge 0$
- Correlation unity on diagonal: $Corr(i, i) = 1.0$
- Correlation boundedness: $-1.0 \le Corr(i, j) \le 1.0$
```python
from autogenesis_property_verifier import CovarianceInvariantValidator

report = CovarianceInvariantValidator.validate_covariance(matrix)
assert report["valid"], f"Violations: {report['violations']}"
print(f"Min eigenvalue: {report['min_eigenvalue']}")
```

### 3. Topological Acyclicity & Iterative Cycle Pinpointing
Guarantees dependency graphs are acyclic and deterministic using Kahn's algorithm with deterministic tie-breaking. If a cyclic dependency exists, an iterative 3-color DFS traces the exact closed loop on an explicit heap stack, guaranteeing safe execution on graphs of 1,000+ nodes without recursion limits or `RecursionError`:
```python
from autogenesis_property_verifier import TopologicalInvariantValidator

res = TopologicalInvariantValidator.validate_and_order(nodes, edges)
if not res["acyclic"]:
    print(f"Deadlock detected! Cycle: {' -> '.join(res['cycle_path'])}")
else:
    print(f"Deterministic execution sequence: {res['execution_order']}")
```

### 4. Strict Contract Schema Validation
Enforces required fields, types, numeric thresholds, regular expression patterns, and custom invariant predicates before accepting tool or API payloads.

### 5. High-Efficiency Streaming Processor (Gap 5 Remediation)
Protects memory-constrained environments (such as Android Droidspaces containers) from Out-Of-Memory (OOM) crashes by streaming large datasets or spilling into lightweight SQLite buffers. Supports arbitrary dictionary records without schema lock-in, guaranteeing peak heap usage strictly under 2.0 MiB:
```python
from autogenesis_property_verifier import StreamingRecordProcessor

processor = StreamingRecordProcessor()
res = processor.process_stream_to_spill_buffer(
    record_stream,
    filter_predicate=lambda r: r.get("status") == "active" and r.get("score", 0) > 50,
    value_extractor=lambda r: float(r.get("value", 0.0))
)
print(f"Peak memory: {res['peak_mem_kib']} KiB (< 2048 KiB: {res['memory_compliant']})")
```
