"""General questions: the same Meta model, with optional bounded optimization."""
import asyncio
import hashlib
import json
import time
from . import meta_ai, modal_worker, spreadsheet_output, optimizer_output
from .benchmark import usage_summary, verified_worker
from .protocol import SCHEMA, MAX_BITS, canonical, prepare
from optimizer.specs import Spec
from optimizer.policy import GPU_BUDGET

COMMON = '''Answer the user's question clearly and accurately. Reply in the user's language unless
another language is explicitly requested. If important information is missing, ask for it.
You have no web browser, live search or ability to take actions outside the listed tools.
Do not invent facts, data, sources, measurements, tool use, correctness proofs or timings.
If the question has a mistaken premise, explain it. Acknowledge uncertainty when appropriate.
Return a useful text answer. Code may be shown as text, but is never executed by this application.'''

ASSISTED = '''You may use optimize_binary_problem once, only if the user's request contains a
supported binary optimization task and enough numerical data. For ordinary questions, answer
normally without a tool. Never turn a factual, creative or explanatory question into an invented
optimization problem. Never omit a requested constraint to fit the tool.
Supported spec_json shapes (JSON encoded as a string):
- {"kind":"channels","weights":[...]}: symmetric nonnegative square matrix, zero diagonal;
  split events into two sessions, no capacities, deadlines or timetable constraints.
- {"kind":"partition","durations":[...]}: positive loads; two groups, squared imbalance only.
- {"kind":"projects","benefits":[...],"conflicts":[[1,2],...]}: positive benefits and hard
  forbidden pairs with 1-based indices; no budget constraint.
- {"kind":"assignment","costs":[[...],...]}: square nonnegative one-to-one assignment costs.
- {"kind":"custom","matrix":[[...],...],"offset":0}: explicitly supplied binary quadratic
  objective x.T @ Q @ x + offset. Use all entries; symmetric off-diagonal entries count twice.
Use 2..64 binary decisions total; an n by n assignment uses n*n bits, so n<=8.
Do not specify size for actual arrays, and do not invent coefficients or drop constraints.
Only when the user explicitly asks for synthetic/demo/generated data, these generated specs are
allowed: {"kind":"channels","variant":"standard","size":16,"seed":42}, partition/coupled,
projects/interactions, assignment/two_pools or custom/dense, size 4..64. Explicitly call them synthetic.
If required data is missing, or constraints cannot be represented, explain the limit and ask for
clarification; you may still give useful general guidance without the tool.
formulation_summary must briefly explain how the supplied numbers and constraints map to the spec.
After a tool response, explain the returned solution and its limitations. Do not claim it is globally
optimal or that the question-to-math translation was independently verified. Do not request another tool.'''

TOOL = {'type': 'function', 'function': {
    'name': 'optimize_binary_problem',
    'description': 'Solve one supported binary optimization problem using Simulated Bifurcation and bounded general tabu refinement on NVIDIA via Modal. Optional: never use for ordinary knowledge or writing questions.',
    'parameters': {'type': 'object', 'properties': {
        'spec_json': {'type': 'string', 'description': 'JSON object matching one supported mathematical spec; at most 64 binary decisions.'},
        'formulation_summary': {'type': 'string', 'description': 'How the user data and constraints map to the spec.'}},
        'required': ['spec_json', 'formulation_summary'], 'additionalProperties': False}}}

CSV_TOOL_INSTRUCTION = '''For this spreadsheet run, respond only with JSON matching the response
schema. Either return the final {summary, columns, rows} spreadsheet, or request the optimizer
with {"optimizer_request":{"spec_json":"...","formulation_summary":"..."}}.
These alternatives are mutually exclusive. Do not emit native function/tool calls.
Invoice arithmetic, totals, subtotals, grouping, overdue checks and rankings are spreadsheet
calculations, not binary optimization. For these, return the final table directly.
An optimizer request ends your response. The application validates the solver result and builds
the CSV itself; there is no second model call to repair or rewrite it. The generated report contains
decisions, objective and constraint status; a matching one-to-one CSV also includes original cells,
assigned costs and savings against a valid current allocation. Other source rows are preserved
separately from solver-indexed decisions. Use a direct table response instead if the requested
spreadsheet transformation cannot be represented by this report. Never invent additional tool use.'''

CSV_ASSISTED_SCHEMA = {'anyOf': [spreadsheet_output.SCHEMA, {
    'type': 'object', 'properties': {'optimizer_request': TOOL['function']['parameters']},
    'required': ['optimizer_request'], 'additionalProperties': False}]}


def tool_problem(arguments):
    args = meta_ai.parse_json(arguments)
    if set(args) != {'spec_json', 'formulation_summary'}:
        raise ValueError('invalid_tool_call')
    text, summary = args['spec_json'], args['formulation_summary']
    if not isinstance(text, str) or len(text) > 100000 or not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 4000:
        raise ValueError('invalid_tool_call')
    obj = meta_ai.parse_json(text)
    # Bound input dimensions before building a matrix, including assignment expansion.
    if obj.get('kind') not in ('channels', 'partition', 'projects', 'assignment', 'custom'):
        raise ValueError('meta_invalid_plan')
    for key in ('matrix', 'weights', 'durations', 'benefits', 'costs'):
        values = obj.get(key)
        if isinstance(values, list) and (len(values) > MAX_BITS or any(isinstance(v, list) and len(v) > MAX_BITS for v in values)):
            raise ValueError('comparison_size_limit')
    if isinstance(obj.get('conflicts'), list) and len(obj['conflicts']) > MAX_BITS * (MAX_BITS - 1) // 2:
        raise ValueError('comparison_size_limit')
    try:
        spec = Spec.model_validate(obj)
        if spec.kind == 'custom' and spec.variant == 'standard' and spec.matrix is None:
            raise ValueError()
    except ValueError:
        raise ValueError('meta_invalid_plan') from None
    p, public, _ = prepare(spec.model_dump(exclude_none=True))
    return p, public, summary.strip()


async def answer_arm(name, question, digest, config, optimizer_available, progress, *, output_format="text"):
    start = time.perf_counter()
    calls = []
    evidence = {'question_sha256': digest, 'model_configuration': config.public(), 'calls': calls,
                'tool_requested': False, 'tool_used': False, 'gpu_execution_verified': False,
                'solver_solution_valid': None,
                'tool_available': name == 'assisted' and optimizer_available}
    csv_output = output_format == 'csv'
    prompt = COMMON if not csv_output else COMMON.replace('Return a useful text answer. Code may be shown as text, but is never executed by this application.', spreadsheet_output.PROMPT)
    evidence['output_format'] = output_format
    if name == 'assisted':
        prompt += '\n' + (ASSISTED if optimizer_available else 'No optimization tool is available in this run. Answer normally and do not claim to have used one.')
        if csv_output and optimizer_available:
            prompt += '\n' + CSV_TOOL_INSTRUCTION
    response_schema = (CSV_ASSISTED_SCHEMA if name == 'assisted' and optimizer_available else spreadsheet_output.SCHEMA) if csv_output else None
    if csv_output:
        prompt += '\nRequired JSON schema: ' + canonical(response_schema)
        evidence['output_contract'] = 'provider_json_schema_and_local_table_validation'
        evidence['optimizer_request_transport'] = 'json_envelope' if name == 'assisted' and optimizer_available else None
    messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': question}]
    try:
        progress(name, 'answering')
        msg, ev = await meta_ai.complete(messages, config,
            tools=[TOOL] if name == 'assisted' and optimizer_available and not csv_output else None,
            json_mode=csv_output, response_schema=response_schema,
            timeout_seconds=meta_ai.ANSWER_TIMEOUT_SECONDS)
        calls.append(ev)
        tool_calls = msg.get('tool_calls')
        tool_args = None
        if csv_output:
            if tool_calls:
                raise ValueError('invalid_tool_call')
            try:
                obj = meta_ai.parse_json(msg.get('content'))
            except meta_ai.AIError:
                obj = {}  # The table validator below records the precise failure.
            if 'optimizer_request' in obj:
                evidence['tool_requested'] = True
                if name != 'assisted' or not optimizer_available or set(obj) != {'optimizer_request'}:
                    raise ValueError('invalid_tool_call')
                tool_args = canonical(obj['optimizer_request'])
        elif tool_calls:
            evidence['tool_requested'] = True
            if name != 'assisted' or not optimizer_available or not isinstance(tool_calls, list) or len(tool_calls) != 1:
                raise ValueError('invalid_tool_call')
            tc = tool_calls[0]
            if not isinstance(tc, dict) or tc.get('type') != 'function' or not isinstance(tc.get('id'), str) or not tc['id'] or tc.get('function', {}).get('name') != 'optimize_binary_problem':
                raise ValueError('invalid_tool_call')
            tool_args = tc['function'].get('arguments')
            if not isinstance(tool_args, str):
                raise ValueError('invalid_tool_call')
        table = None
        if tool_args is not None:
            p, public, summary = tool_problem(tool_args)
            evidence.update(tool_problem=public, formulation_summary=summary,
                formulation_verified_against_question=False)
            progress(name, 'optimizer_running')
            evidence['tool_used'] = True
            raw = await modal_worker.optimize(p.spec.model_dump(exclude_none=True), public['sha256'], p.spec.seed)
            evidence['tool_result'] = raw
            checked = verified_worker(raw, public['sha256'], p)
            evidence.update(gpu_execution_verified=True, tool_validation=checked,
                solver_solution_valid=checked['decoded'].get('feasible') is True)
            if not evidence['solver_solution_valid']:
                raise ValueError('optimizer_infeasible')
            reply = {'problem_sha256': public['sha256'], **checked, 'method': 'Simulated Bifurcation with bounded GPU tabu refinement',
                'hardware': raw['hardware'], 'formulation_summary': summary,
                'formulation_verified_against_question': False, 'optimum_proven': False}
            if csv_output:
                answer, table = optimizer_output.build(p, checked, question)
                evidence['final_answer_source'] = 'verified_optimizer_result'
                evidence['final_model_call_skipped'] = True
            else:
                messages.extend([msg, {'role': 'tool', 'tool_call_id': tc['id'], 'content': canonical(reply)}])
                progress(name, 'meta_reviewing')
                msg, ev = await meta_ai.complete(messages, config, tools=[TOOL], tool_choice='none',
                    timeout_seconds=meta_ai.ANSWER_TIMEOUT_SECONDS)
                calls.append(ev)
                if msg.get('tool_calls'):
                    raise ValueError('invalid_tool_call')
        if table is None:
            answer = msg.get('content')
            if not isinstance(answer, str) or not answer.strip():
                raise meta_ai.AIError('meta_format')
            if csv_output:
                answer, table = spreadsheet_output.parse_answer(answer)
        if table is not None:
            evidence['csv_validation'] = {'status': 'valid', 'rows': len(table['rows']),
                'columns': len(table['columns']), 'normalizations': table['normalizations'],
                'arithmetic_verified': table['content_verified'],
                'verification_scope': table.get('verification_scope', 'Structure only.'),
                'source_mapping_verified': table.get('source_mapping_verified', False)}
        outcome = {'status': 'completed', 'answer': answer, 'answer_quality_verified': False}
        if table is not None:
            outcome['csv_solution'] = table
    except asyncio.CancelledError:
        raise
    except meta_ai.AIError as exc:
        if hasattr(exc, 'validation_detail'):
            evidence['csv_validation'] = exc.validation_detail
        if exc.evidence and not any(exc.evidence is c for c in calls):
            calls.append(exc.evidence)
        outcome = {'status': 'failed', 'error': str(exc), 'provider_status': exc.provider_status}
    except ValueError as exc:
        allowed = {'invalid_tool_call', 'meta_invalid_plan', 'comparison_size_limit',
                   'invalid_solution_length', 'invalid_binary_solution', 'invalid_objective',
                   'gpu_verification_failed', 'objective_verification_failed', 'optimizer_infeasible',
                   'optimizer_source_mismatch', 'optimizer_budget_mismatch', 'quality_verification_failed'}
        outcome = {'status': 'failed', 'error': str(exc) if str(exc) in allowed else 'compute_failed'}
    except Exception as exc:
        code = {'NotFoundError': 'modal_app_not_found', 'AuthError': 'modal_access_denied',
                'PermissionDeniedError': 'modal_access_denied', 'FunctionTimeoutError': 'job_timeout',
                'TimeoutError': 'job_timeout'}.get(type(exc).__name__, 'compute_failed')
        outcome = {'status': 'failed', 'error': code}
    outcome.update(evidence=evidence, model_calls=len(calls), usage=usage_summary(calls),
        meta_ms=sum(c.get('elapsed_ms', 0) for c in calls), end_to_end_ms=(time.perf_counter() - start) * 1000,
        cost_usd=None, cost_note='Dollar cost is not measured. Token usage is recorded when reported.')
    return outcome


async def compare(question, publish, config=None, optimizer_available=None, *, output_format="text"):
    started = time.perf_counter()
    config = config or meta_ai.configuration()
    available = modal_worker.configured() if optimizer_available is None else optimizer_available
    digest = hashlib.sha256(question.encode('utf-8')).hexdigest()
    engines, states = {}, {}
    result = {'schema_version': SCHEMA, 'mode': 'question', 'complete': False, 'output_format': output_format,
        'question': {'text': question, 'sha256': digest, 'hash_convention': 'SHA256 of the exact UTF-8 user message.'},
        'protocol': {'model': config.public(), 'repetitions': 1, 'same_question_sha256': digest,
            'output_format': output_format,
            'output_contract': 'JSON schema for model tables; verified optimizer CSVs are generated by the server without another model call. Model tables have structure checks only.' if output_format == 'csv' else 'Text answer.',
            'optimizer_request_transport': 'json_envelope' if output_format == 'csv' else 'native_tool_call',
            'model_call_timeout_seconds': meta_ai.ANSWER_TIMEOUT_SECONDS,
            'job_deadline_seconds': 400,
            'optimizer_available': available, 'quality_verified': False,
            'direct': 'One Meta call without tools.',
            'assisted': 'One Meta call with an optional optimizer. CSV tool results are rendered directly; plain-text questions may use one final Meta call only after a feasible result.',
            'gpu_budget': dict(GPU_BUDGET),
            'optimizer_method': 'Two Simulated Bifurcation trials plus bounded GPU tabu refinement. Original candidates are retained; feasibility is checked before cost selection.',
            'execution': 'Independent concurrent requests with the identical user message and frozen model settings. The assisted system prompt describes its optional tool.',
            'timing': 'Total wall time per path includes all model calls, tool formulation/validation, remote GPU startup/computation and final answer. The optional explanation is separate.',
            'interpretation': 'Response latency is measured. Text accuracy, completeness and equivalence are not automatically checked. A faster answer is not proof of a better answer or an optimizer benefit.',
            'formulation': 'If used, the model-generated tool problem is recorded and numerically validated. Its correspondence to the user question is not independently verified.',
            'web_search_available': False}, 'engines': engines}

    def progress(name, stage):
        states[name] = stage
        publish(stage='running', partial={**result, 'engines': dict(engines)}, arm_stages=dict(states))

    async def one(name):
        engines[name] = await answer_arm(name, question, digest, config, available, progress, output_format=output_format)
        progress(name, engines[name]['status'])

    tasks = [asyncio.create_task(one(name)) for name in ('meta', 'assisted')]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    a, b = engines['meta'], engines['assisted']
    both = all(e['status'] == 'completed' for e in (a, b))
    result.update(complete=True,
        comparison={'both_completed': both, 'quality_verified': False,
                    'assisted_time_ratio': a['end_to_end_ms'] / max(b['end_to_end_ms'], 1e-9) if both else None,
                    'optimizer_used': b['evidence']['tool_used'],
                    'gpu_execution_verified': b['evidence']['gpu_execution_verified'],
                    'solver_solution_valid': b['evidence']['solver_solution_valid'],
                    'basis': 'Completed text response latency only. No objective comparison or overall quality winner.'},
        hardware=b['evidence'].get('tool_result', {}).get('hardware'),
        total_request_ms=(time.perf_counter() - started) * 1000)
    return result
