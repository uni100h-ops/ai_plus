"""Async private Modal calls, including cancellation of an active GPU task."""
import asyncio
import os
import time


def configured():
    return bool(os.getenv('MODAL_TOKEN_ID') and os.getenv('MODAL_TOKEN_SECRET'))


async def optimize(spec, problem_sha256, seed):
    import modal
    start = time.perf_counter()
    call = None
    completed = False
    try:
        fn = modal.Function.from_name(os.getenv('MODAL_APP_NAME', 'metaquant-problems-ai'),
            'optimize_problem_v2', environment_name=os.getenv('MODAL_ENVIRONMENT', 'main') or 'main')
        call = await fn.spawn.aio(spec, problem_sha256, seed)
        result = await call.get.aio(timeout=240)
        result['remote_wall_ms'] = (time.perf_counter() - start) * 1000
        completed = True
        return result
    finally:
        # Cancelling an awaiting HTTP request alone does not cancel a Modal task.
        if call is not None and not completed:
            try:
                await asyncio.wait_for(asyncio.shield(call.cancel.aio(terminate_containers=True)), timeout=10)
            except Exception:
                pass
