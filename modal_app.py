"""Private GPU worker deployed by the Render build pipeline."""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parent
# A separate Modal app keeps the previous worker deployment available for rollback.
app = modal.App('metaquant-problems-ai')
image = (modal.Image.debian_slim(python_version='3.12')
    .pip_install('torch==2.6.0', index_url='https://download.pytorch.org/whl/cu124')
    .pip_install('numpy==2.5.4', 'pydantic==2.14.1', 'simulated-bifurcation==2.0.0')
    .env({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
    .add_local_dir(ROOT / 'optimizer', remote_path='/root/optimizer')
    .add_local_dir(ROOT / 'server', remote_path='/root/server'))

with image.imports():
    import torch


@app.function(image=image, gpu=['L4', 'T4'], cpu=2, memory=4096,
              timeout=240, scaledown_window=60, min_containers=0, max_containers=1, retries=0)
def optimize_problem_v2(spec_data: dict, problem_sha256: str, seed: int):
    import sys
    sys.path.insert(0, '/root')
    from server.protocol import prepare, SCHEMA
    from optimizer.gpu import solve
    p, public, _ = prepare(spec_data)
    if public['sha256'] != problem_sha256:
        raise ValueError('problem_hash_mismatch')
    result = solve(p, seed)
    result.update(schema_version=SCHEMA, problem_sha256=problem_sha256, provider='Modal')
    return result
