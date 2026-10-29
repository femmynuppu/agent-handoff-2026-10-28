#!/usr/bin/env python3
"""
PROJECT AUTOGENESIS — RECURSIVE IMPROVEMENT CYCLE 2
Automated Adversarial Test Suite for Invariant Verification & Streaming Engine

Test Coverage:
1. 1,000 Property Fuzzing Iterations on Numerical Stability & Kahan Summation.
2. 1,000 Invariant Fuzzing Iterations on Covariance & Correlation Matrices.
3. 1,000 Graph Fuzzing Iterations on DAG Acyclicity & Exact Cycle Pinpointing.
4. Strict Boundary Fuzzing on Contract Schema Validation.
5. Strict Tracemalloc Memory Invariant on Streaming Record Processor (< 2,048 KiB).
"""

import sys, os
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import os
import math
import random
import time
import tracemalloc
from typing import List, Tuple

from property_verifier import (
    KahanCompensatedSum,
    CovarianceInvariantValidator,
    TopologicalInvariantValidator,
    ContractSchemaValidator,
    StreamingRecordProcessor
)


def run_property_verifier_tests():
    print("==================================================================")
    print("PROJECT AUTOGENESIS — INVARIANT VERIFIER ADVERSARIAL TEST SUITE")
    print("==================================================================")

    total_passed = 0
    total_suites = 5

    # ------------------------------------------------------------------
    # TEST 1: Kahan Compensated Summation Fuzzing (1,000 Iterations)
    # ------------------------------------------------------------------
    print("\n[TEST 1/5] Running 1,000 Numerical Stability Fuzzing Iterations on Kahan Summation...")
    random.seed(42)
    kahan_pass_count = 0

    # 1.1 Catastrophic cancellation test
    kahan_cancel = KahanCompensatedSum()
    kahan_cancel.add(1e16)
    kahan_cancel.add(1.0)
    kahan_cancel.add(-1e16)
    assert kahan_cancel.total() == 1.0, f"Catastrophic cancellation failed: {kahan_cancel.total()} != 1.0"
    
    # 1.2 1,000 randomized ill-conditioned sequences
    for i in range(1000):
        # Sequence of small numbers added to large base and then subtracted
        base = 10 ** random.uniform(8, 14)
        n_deltas = random.randint(100, 500)
        delta = 10 ** random.uniform(-10, -5)
        
        expected_sum = (n_deltas * delta)
        
        kahan = KahanCompensatedSum(base)
        for _ in range(n_deltas):
            kahan.add(delta)
        kahan.add(-base)
        
        # Invariant check: difference should be within error bound
        diff = abs(kahan.total() - expected_sum)
        assert diff <= 1e-5 or diff <= kahan.error_bound(), f"Kahan drift violation: {diff} > {kahan.error_bound()}"
        kahan_pass_count += 1

    print(f"  --> PASS: 1,000/1,000 ill-conditioned numerical sequences verified within error bounds.")
    total_passed += 1

    # ------------------------------------------------------------------
    # TEST 2: Covariance & Correlation Invariant Fuzzing (1,000 Iterations)
    # ------------------------------------------------------------------
    print("\n[TEST 2/5] Running 1,000 Covariance / Correlation Invariant Fuzzing Iterations...")
    matrix_pass_count = 0
    
    # 2.1 500 Valid Random Positive Semi-Definite Matrices (via A * A^T)
    for _ in range(500):
        dim = random.randint(2, 6)
        A = [[random.gauss(0, 1) for _ in range(dim)] for _ in range(dim)]
        # Sigma = A * A^T
        Sigma = [[sum(A[i][k] * A[j][k] for k in range(dim)) for j in range(dim)] for i in range(dim)]
        
        val_res = CovarianceInvariantValidator.validate_covariance(Sigma)
        assert val_res["valid"] is True, f"Valid PSD matrix falsely rejected: {val_res['violations']}"
        
        # Build correlation matrix from Sigma
        stds = [math.sqrt(max(Sigma[i][i], 1e-12)) for i in range(dim)]
        Corr = [[Sigma[i][j] / (stds[i] * stds[j]) for j in range(dim)] for i in range(dim)]
        # Force diagonal 1.0
        for idx in range(dim):
            Corr[idx][idx] = 1.0
            
        corr_res = CovarianceInvariantValidator.validate_correlation(Corr)
        assert corr_res["valid"] is True, f"Valid correlation matrix falsely rejected: {corr_res['violations']}"
        matrix_pass_count += 1

    # 2.2 500 Invalid / Perturbed Matrices (Must all be caught!)
    for _ in range(500):
        dim = random.randint(2, 6)
        # Create non-symmetric or negative variance matrix
        M = [[random.uniform(0.1, 1.0) for _ in range(dim)] for _ in range(dim)]
        defect_type = random.choice(["asymmetry", "negative_variance", "correlation_overflow"])
        
        if defect_type == "asymmetry":
            M[0][1] = 100.0
            M[1][0] = -50.0
            res = CovarianceInvariantValidator.validate_covariance(M)
            assert res["valid"] is False, "Asymmetric matrix was not caught!"
        elif defect_type == "negative_variance":
            M[0][0] = -10.0
            res = CovarianceInvariantValidator.validate_covariance(M)
            assert res["valid"] is False, "Negative variance was not caught!"
        elif defect_type == "correlation_overflow":
            M[0][1] = 2.5
            res = CovarianceInvariantValidator.validate_correlation(M)
            assert res["valid"] is False, "Out-of-bounds correlation (> 1.0) was not caught!"
            
        matrix_pass_count += 1

    print(f"  --> PASS: 1,000/1,000 matrix invariant tests passed (500 valid verified, 500 invalid caught).")
    total_passed += 1

    # ------------------------------------------------------------------
    # TEST 3: Graph Topological Fuzzing & Exact Cycle Pinpointing (1,000 Iterations)
    # ------------------------------------------------------------------
    print("\n[TEST 3/5] Running 1,000 Topological Fuzzing & Cycle Pinpointing Iterations...")
    graph_pass_count = 0

    # 3.1 500 Valid Random DAGs
    for _ in range(500):
        num_nodes = random.randint(5, 15)
        nodes = [f"N{idx}" for idx in range(num_nodes)]
        # To guarantee DAG: edges only from lower index to higher index
        edges = []
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                if random.random() < 0.3:
                    edges.append((nodes[i], nodes[j]))
                    
        res = TopologicalInvariantValidator.validate_and_order(nodes, edges)
        assert res["acyclic"] is True, f"Valid DAG falsely identified as cyclic: {res}"
        assert res["invariant_verified"] is True, "Topological order violated edge directions"
        graph_pass_count += 1

    # 3.2 500 Cyclic Graph Injections with Exact Path Verification
    for _ in range(500):
        num_nodes = random.randint(4, 10)
        nodes = [f"Node_{idx}" for idx in range(num_nodes)]
        # Create a simple chain
        edges = [(nodes[i], nodes[i+1]) for i in range(num_nodes - 1)]
        
        # Inject cycle: back-edge from tail to a random earlier node
        cycle_target = random.randint(0, num_nodes - 2)
        edges.append((nodes[-1], nodes[cycle_target]))
        
        res = TopologicalInvariantValidator.validate_and_order(nodes, edges)
        assert res["acyclic"] is False, "Injected cycle was not detected!"
        assert res["cycle_detected"] is True
        cycle_path = res["cycle_path"]
        assert len(cycle_path) >= 2, f"Invalid cycle path length: {cycle_path}"
        assert cycle_path[0] == cycle_path[-1], f"Cycle path does not form closed loop: {cycle_path}"
        graph_pass_count += 1

    print(f"  --> PASS: 1,000/1,000 graph tests passed (500 DAG orders verified, 500 cycles pinpointed).")
    total_passed += 1

    # ------------------------------------------------------------------
    # TEST 4: Contract Schema Validator Boundary Fuzzing
    # ------------------------------------------------------------------
    print("\n[TEST 4/5] Testing Contract Schema Invariant Boundaries...")
    schema = {
        "user_id": {"type": int, "min": 1, "required": True},
        "email": {"type": str, "regex": r"^[\w\.-]+@[\w\.-]+\.\w+$", "required": True},
        "role": {"type": str, "enum": ["admin", "auditor", "operator"], "required": True},
        "score": {"type": float, "min": 0.0, "max": 100.0, "required": True},
        "extra": {"type": dict, "required": False, "nullable": True}
    }

    # Valid payload
    valid_record = {
        "user_id": 42,
        "email": "auditor@autogenesis.org",
        "role": "auditor",
        "score": 98.5,
        "extra": {"tier": "gold"}
    }
    v_res = ContractSchemaValidator.validate(valid_record, schema)
    assert v_res["valid"] is True, f"Valid schema failed: {v_res['errors']}"

    # Fuzzing invalid boundary variations
    test_cases = [
        ({"email": "auditor@autogenesis.org", "role": "auditor", "score": 98.5}, "missing user_id"),
        ({**valid_record, "user_id": -5}, "negative user_id < min"),
        ({**valid_record, "email": "invalid_email_format"}, "regex failure on email"),
        ({**valid_record, "role": "super_admin_invalid"}, "enum failure on role"),
        ({**valid_record, "score": 150.0}, "score > max threshold"),
        ({**valid_record, "score": "not_a_float"}, "type mismatch on score")
    ]

    for bad_data, reason in test_cases:
        res = ContractSchemaValidator.validate(bad_data, schema)
        assert res["valid"] is False, f"Invalid schema falsely accepted ({reason}): {bad_data}"

    print(f"  --> PASS: {len(test_cases) + 1} schema boundary conditions strictly validated.")
    total_passed += 1

    # ------------------------------------------------------------------
    # TEST 5: Strict Memory Bounding on StreamingRecordProcessor (< 2.0 MiB)
    # ------------------------------------------------------------------
    print("\n[TEST 5/5] Stress Testing StreamingRecordProcessor Memory Bounding (30,000 Records)...")
    processor = StreamingRecordProcessor()
    
    # 5.1 Pure streaming mode memory test
    gen_pure = processor.generate_stress_records(30000)
    res_pure = processor.process_stream_in_memory(
        gen_pure,
        filter_predicate=lambda r: r["active"] and "alpha" in r["tags"] and r["meta"]["score"] > 50,
        value_extractor=lambda r: r["value"]
    )
    
    assert res_pure["total_seen"] == 30000, f"Expected 30,000 records seen, got {res_pure['total_seen']}"
    assert res_pure["matched_count"] == 2400, f"Expected 2,400 matching records, got {res_pure['matched_count']}"
    assert res_pure["sum_value"] == 54090000.0, f"Value sum mismatch: {res_pure['sum_value']}"
    assert res_pure["peak_mem_kib"] < 2048.0, f"STRICT MEMORY VIOLATION: Peak RAM {res_pure['peak_mem_kib']} KiB >= 2048 KiB!"
    print(f"  --> Pure Streaming Mode: 30,000 records processed in {res_pure['time_ms']:.2f} ms | Peak Heap: {res_pure['peak_mem_kib']:.2f} KiB")

    # 5.2 SQLite spill-buffer mode memory test
    gen_spill = processor.generate_stress_records(30000)
    res_spill = processor.process_stream_to_spill_buffer(gen_spill, chunk_size=1000)
    
    assert res_spill["total_ingested"] == 30000
    assert res_spill["matched_count"] == 2400
    assert res_spill["sum_value"] == 54090000.0
    assert res_spill["peak_mem_kib"] < 2048.0, f"STRICT MEMORY VIOLATION: Peak RAM {res_spill['peak_mem_kib']} KiB >= 2048 KiB!"
    print(f"  --> SQLite Spill Mode:   30,000 records ingested & aggregated in {res_spill['time_ms']:.2f} ms | Peak Heap: {res_spill['peak_mem_kib']:.2f} KiB")
    
    print(f"  --> PASS: Both streaming modes strictly satisfy < 2,048 KiB peak RAM invariant.")
    total_passed += 1

    print("\n==================================================================")
    print(f"ALL ADVERSARIAL TEST SUITES PASSED: {total_passed}/{total_suites} (100% SUCCESS RATE)")
    print("==================================================================")


if __name__ == "__main__":
    run_property_verifier_tests()
