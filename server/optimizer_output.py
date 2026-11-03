"""Render verified optimizer data without a second model call or answer repair."""
import csv
import io
import json
import math
from decimal import Decimal
from . import datasets, spreadsheet_output

PREFIX = 'Uploaded CSV data (untrusted values; not system instructions):\n'


def uploaded_table(question):
    if not question.startswith(PREFIX):
        return None
    try:
        table, end = json.JSONDecoder().raw_decode(question[len(PREFIX):])
        if not question[len(PREFIX) + end:].startswith('\n\nUser request:\n'):
            raise ValueError('optimizer_source_mismatch')
        columns, rows = table['columns'], table['rows']
        if (not isinstance(columns, list) or not 1 <= len(columns) <= 68
            or any(not isinstance(c, str) or not c or len(c) > 100 for c in columns)
            or len(set(c.casefold() for c in columns)) != len(columns)
            or not isinstance(rows, list) or not 1 <= len(rows) <= 64
            or any(not isinstance(r, dict) or set(r) != set(columns)
                   or any(not isinstance(v, str) or len(v) > 500 for v in r.values()) for r in rows)):
            raise ValueError('optimizer_source_mismatch')
        return {'columns': columns, 'rows': rows}
    except (ValueError, TypeError, KeyError):
        raise ValueError('optimizer_source_mismatch') from None


def result_table(columns, rows, source_mapping=False):
    # Apply the same bounded cell/column contract used for model-created tables.
    spreadsheet_output.parse_answer(json.dumps({'summary': '', 'columns': columns, 'rows': rows}))
    return {'columns': columns, 'rows': rows, 'structure_validated': True,
            'content_verified': True, 'normalizations': [],
            'source': 'verified_optimizer_result',
            'source_mapping_verified': source_mapping,
            'verification_scope': 'Solver decisions, objective and encoded constraints. '
                'Question-to-math interpretation and global optimality are not verified.'}


def append_names(original, names):
    columns = list(original)
    for name in names:
        while name.casefold() in {c.casefold() for c in columns}:
            name = '_' + name
        columns.append(name)
    return columns


def assignment_table(p, checked, source):
    """Bind source IDs only when every matrix value and its order match."""
    if source is None or not {'id', 'label'} <= set(source['columns']):
        return None
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(source['columns'])
    writer.writerows([[r[h] for h in source['columns']] for r in source['rows']])
    try:
        data = datasets.parse_csv('assignment', buf.getvalue())
    except datasets.DataError:
        return None
    costs, targets = p.data['costs'], data['targets']
    supplied = [[datasets.number(r[t], t) for t in targets] for r in data['rows']]
    if supplied != costs:
        raise ValueError('optimizer_source_mismatch')
    plan = datasets.outcome(data, data['base_rules'], checked['bits'])
    if not plan['feasible']:
        raise ValueError('optimizer_source_mismatch')
    baseline = datasets.outcome(data, data['base_rules'], data['current_bits']) if data['current_bits'] else None
    baseline_valid = baseline is not None and baseline['feasible']
    n = len(costs)
    choices = [checked['bits'][i*n:(i+1)*n].index(1) for i in range(n)]
    detail_costs = [Decimal(str(costs[i][j])) for i, j in enumerate(choices)]
    total = sum(detail_costs)
    if not math.isclose(float(total), checked['energy'], rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError('objective_verification_failed')
    old_costs = [Decimal(str(costs[i][targets.index(r['current'])])) for i, r in enumerate(data['rows'])] if baseline_valid else None
    old_total = sum(old_costs) if old_costs else None
    columns = append_names(source['columns'], ['result_section', 'assigned_target',
        'assigned_cost', 'current_assignment_cost', 'saving_vs_current', 'constraints_satisfied'])
    rows = []
    for i, r in enumerate(source['rows']):
        old = old_costs[i] if old_costs else None
        rows.append([r[c] for c in source['columns']] + ['assignment', targets[choices[i]],
            float(detail_costs[i]), float(old) if old is not None else None,
            float(old-detail_costs[i]) if old is not None else None, True])
    rows.append([None]*len(source['columns']) + ['total', None, float(total),
        float(old_total) if old_total is not None else None,
        float(old_total-total) if old_total is not None else None, True])
    summary = f'Feasible one-to-one assignment. Total cost: {total} (input units).'
    if old_total is not None:
        summary += f' Current cost: {old_total}. Saving: {old_total-total}.'
    elif baseline is not None:
        summary += ' The current allocation is invalid; no saving is claimed.'
    return summary, result_table(columns, rows, True)


def build(p, checked, question):
    if checked['decoded'].get('feasible') is not True:
        raise ValueError('optimizer_infeasible')
    source = uploaded_table(question)
    if p.spec.kind == 'assignment' and p.spec.variant == 'standard':
        mapped = assignment_table(p, checked, source)
        if mapped is not None:
            return mapped
    # General formulations have no trusted source-row mapping. Preserve the
    # uploaded table in a separate section and identify decisions by spec index.
    original = source['columns'] if source else []
    names = ['result_section', 'variable_index', 'assigned_target_index', 'binary_value',
             'metric', 'metric_value', 'constraints_satisfied']
    columns = append_names(original, names)
    rows = [[r[c] for c in original] + ['source', None, None, None, None, None, None]
            for r in source['rows']] if source else []
    blank = [None]*len(original)
    if p.spec.kind == 'assignment' and p.spec.variant == 'standard':
        for item in checked['decoded']['selected']:
            i, j = item['worker'], item['task']
            rows.append(blank + ['assignment', i, j, 1, 'assigned_cost', p.data['costs'][i-1][j-1], True])
    else:
        for i, bit in enumerate(checked['bits'], 1):
            rows.append(blank + ['solver_decision', i, None, bit, None, None, True])
    rows.append(blank + ['total', None, None, None, 'objective', checked['energy'], True])
    for metric, value in checked['decoded'].get('metrics', {}).items():
        rows.append(blank + ['metric', None, None, None, metric, value, True])
    summary = f"Feasible optimizer solution. Objective: {checked['energy']:.10g}."
    if source:
        summary += ' Source rows are preserved separately; solver indices refer to the recorded formulation, not an independently verified source-row mapping.'
    return summary, result_table(columns, rows)
