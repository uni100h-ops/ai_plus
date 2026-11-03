"""Classical NVIDIA CUDA Simulated Bifurcation; no CPU fallback."""
from importlib.metadata import version
import time
import warnings
import torch
from .policy import GPU_BUDGET
from .search import search


def solve(p, seed):
    if not torch.version.cuda or torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError('nvidia_gpu_required')
    device = 'cuda:0'
    torch.cuda.set_device(0)
    torch.set_num_threads(1)
    start = time.perf_counter()
    with torch.inference_mode(), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        bits, energy, quality = search(p, seed, device)
        if bits.shape != (p.n,) or not bool((torch.isfinite(bits) & ((bits == 0) | (bits == 1))).all().item()):
            raise RuntimeError('invalid_sb_solution')
        if not bits.is_cuda or quality['search_device'] != device:
            raise RuntimeError('gpu_tensor_mismatch')
        if not energy.is_cuda or not bool(torch.isfinite(energy).item()):
            raise RuntimeError('invalid_objective')
        torch.cuda.synchronize(0)
        answer = bits.to(torch.int64).cpu().tolist()
        value = float(energy.item())
    return {'bits': answer, 'energy': value, 'solver_ms': (time.perf_counter() - start) * 1000,
        'devices': {'matrix': quality['search_device'], 'solution': str(bits.device),
                    'objective': str(energy.device), 'refinement': quality['search_device']},
        'hardware': {'sb_gpu_vendor': 'NVIDIA CUDA', 'sb_device_name': torch.cuda.get_device_name(0),
            'gpu_execution_verified': True, 'cpu_fallback': False, 'cuda_version': torch.version.cuda,
            'torch_version': str(torch.__version__), 'sb_version': version('simulated-bifurcation')},
        'seed': seed, 'warnings': sorted({type(w.message).__name__ for w in caught}),
        'budget': dict(GPU_BUDGET), 'quality_search': quality}
