"""Single assisted path for API solve requests; no hidden baseline run."""
import hashlib
import time
from . import benchmark, questions
from .protocol import SCHEMA, prepare


async def solve(spec, question, publish, config, optimizer_available):
    started = time.perf_counter()
    states = {}

    def progress(name, stage):
        states[name] = stage
        publish(stage=stage, arm_stages=dict(states))

    if question is not None:
        digest = hashlib.sha256(question.encode('utf-8')).hexdigest()
        outcome = await questions.answer_arm('assisted', question, digest, config, optimizer_available, progress)
        source = {'mode': 'question', 'question': {'text': question, 'sha256': digest},
                  'answer_quality_verified': False,
                  'formulation_verified_against_question': False}
    else:
        p, public, prep_ms = prepare(spec)
        outcome = await benchmark.run_arm('assisted', p, public, config, prep_ms, progress)
        source = {'mode': 'optimization', 'problem': public,
                  'reference': {'known': False, 'energy': None, 'method': 'not_run_in_solve_mode'}}
    evidence = outcome['evidence']
    return {'schema_version': SCHEMA, 'operation': 'solve', 'complete': True, **source,
            'model_configuration': config.public(), 'engine': outcome,
            'optimizer_used': evidence['tool_used'],
            'gpu_execution_verified': evidence.get('gpu_execution_verified',
                evidence.get('tool_result', {}).get('hardware', {}).get('gpu_execution_verified', False)),
            'solver_solution_valid': evidence.get('solver_solution_valid'),
            'total_request_ms': (time.perf_counter() - started) * 1000,
            'timing_note': 'One assisted path only, including model calls, validation and any optimizer startup/computation. No baseline or independent optimality search is run.',
            'quality_note': 'Numerical checks do not verify factual text or question-to-math translation. Speed and improvement are not guaranteed.'}
