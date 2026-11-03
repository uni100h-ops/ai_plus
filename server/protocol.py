"""One immutable numerical problem and independent checks for both AI paths."""
import hashlib
import json
import math
import time
import numpy as np
from optimizer.problems import build_problem, exact_reference
from optimizer.specs import Spec

SCHEMA = 'metaquant-ai-tools-v2'
MAX_BITS = 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def prepare(spec_data):
    start = time.perf_counter()
    spec = Spec.model_validate(spec_data)
    size = spec.size ** 2 if spec.kind == 'assignment' and spec.variant == 'standard' else spec.size
    if size > MAX_BITS:
        raise ValueError('comparison_size_limit')
    p = build_problem(spec)
    if p.n>MAX_BITS:
        raise ValueError('comparison_size_limit')
    public = p.public()
    public.update(Q=p.q.tolist(), offset=p.offset, data=p.data,
                  convention='Minimize x.T @ Q @ x + offset; x contains exactly n integer bits (0 or 1).')
    public.pop('matrix_export', None)
    public.pop('hash_convention', None)
    content = {k: public[k] for k in ('Q', 'offset', 'spec', 'data', 'variables', 'data_source')}
    digest = hashlib.sha256(canonical(content).encode()).hexdigest()
    public['sha256'] = digest
    public['hash_convention'] = 'SHA256 of canonical JSON containing Q, offset, spec, data, variables and data_source.'
    return p, public, (time.perf_counter() - start) * 1000


def validate_bits(p, bits):
    start = time.perf_counter()
    if not isinstance(bits, list) or len(bits) != p.n:
        raise ValueError('invalid_solution_length')
    if any(type(x) is not int or x not in (0, 1) for x in bits):
        raise ValueError('invalid_binary_solution')
    # No repair, rounding, hidden solver, or replacement of an AI answer.
    energy = p.energy(bits)
    if not math.isfinite(energy):
        raise ValueError('invalid_objective')
    return {'bits': bits, 'energy': energy, 'decoded': p.decode(bits),
            'validation_ms': (time.perf_counter() - start) * 1000}


def reference(p):
    start = time.perf_counter()
    r = exact_reference(p)
    r['elapsed_ms'] = (time.perf_counter() - start) * 1000
    return r


def compare_engines(engines, ref):
    for e in engines.values():
        feasible = e.get('status') == 'completed' and e.get('decoded', {}).get('feasible') is True
        gap = max(0.0, e['energy'] - ref['energy']) if feasible and ref['known'] else None
        e.update(optimality_gap_absolute=gap, at_proven_optimum=gap is not None and gap < 1e-6)
    a, b = engines['meta'], engines['assisted']
    valid = all(e.get('status') == 'completed' and e.get('decoded', {}).get('feasible') is True for e in (a, b))
    return {'both_valid': valid,
            'assisted_time_ratio': a['end_to_end_ms'] / max(b['end_to_end_ms'], 1e-9) if valid else None,
            'assisted_objective_minus_meta': b['energy'] - a['energy'] if valid else None,
            'same_objective': abs(b['energy'] - a['energy']) < 1e-6 if valid else None,
            'basis': 'End-to-end latency, including model calls, remote optimizer and independent candidate checking. A failed or infeasible result cannot win.'}
