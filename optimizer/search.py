"""General SB portfolio and bounded tabu refinement; no case-specific rules."""
import time
import torch
import simulated_bifurcation as sb
from .policy import GPU_BUDGET
from .refinement import energy, refine


def valid_candidates(x, shape, device):
    if (x.shape != shape or x.device != device
        or not bool((torch.isfinite(x) & ((x == 0) | (x == 1))).all().item())):
        raise RuntimeError('invalid_sb_solution')


def search(p, seed, device):
    """CPU is supported only for offline tests; gpu.solve enforces production CUDA."""
    q = torch.as_tensor(p.q, dtype=torch.float64, device=device)
    scale = q.abs().amax()
    normalized = (q / scale.clamp_min(1e-12)).to(torch.float32)
    count = GPU_BUDGET['agents_per_trial']
    candidates = []
    trial_seeds = []
    trial_ms = []
    zero_objective = bool((scale == 0).item())
    for trial in GPU_BUDGET['trials']:
        started = time.perf_counter()
        trial_seed = (seed + trial['seed_offset']) % (2**31)
        trial_seeds.append(trial_seed)
        if q.is_cuda:
            torch.cuda.manual_seed(trial_seed)
        else:
            torch.manual_seed(trial_seed)
        if zero_objective:
            x = torch.zeros((count, p.n), dtype=torch.float32, device=q.device)
        else:
            x, _ = sb.minimize(normalized, domain='binary', dtype=torch.float32,
                device=str(q.device), agents=count, max_steps=GPU_BUDGET['steps_per_trial'],
                mode=trial['mode'], heated=trial['heated'], verbose=False,
                early_stopping=False, timeout=None, best_only=False)
        valid_candidates(x, (count, p.n), q.device)
        candidates.append(x.to(torch.float64))
        if q.is_cuda:
            torch.cuda.synchronize(q.device)
        trial_ms.append((time.perf_counter()-started)*1000)
    original = torch.cat(candidates)
    original_energy = energy(q, original, p.offset)
    # Reproduce the previous 128-agent ballistic selection for independent audit.
    baseline_index = int(original_energy[:count].argmin().item())
    baseline_bits = original[baseline_index].to(torch.int64).cpu().tolist()
    refinement_started = time.perf_counter()
    if zero_objective:
        refined = original.clone()
    else:
        refined, _ = refine(q, original, p.offset, steps=GPU_BUDGET['refinement']['steps'])
    valid_candidates(refined, original.shape, q.device)
    refinement_ms = (time.perf_counter()-refinement_started)*1000
    validation_started = time.perf_counter()
    pool = torch.cat([original, refined])  # No original SB vector is discarded.
    energies = energy(q, pool, p.offset)
    if not bool(torch.isfinite(energies).all().item()):
        raise RuntimeError('invalid_objective')
    # Decode on the host only to validate rules; search and objectives stay on CUDA.
    vectors = pool.to(torch.int64).cpu().tolist()
    flags = [p.decode(row)['feasible'] is True for row in vectors]
    feasible = torch.tensor(flags, dtype=torch.bool, device=q.device)
    scores = torch.where(feasible, energies, float('inf')) if any(flags) else energies
    index = int(scores.argmin().item())
    selected = pool[index]
    metadata = {
        'method': 'simulated_bifurcation_with_tabu_refinement',
        'trial_seeds': trial_seeds, 'initial_candidates': len(original),
        'sb_runs_executed': 0 if zero_objective else len(candidates),
        'sb_candidates': 0 if zero_objective else len(original),
        'refined_candidates': len(refined), 'feasible_candidates': sum(flags),
        'baseline_bits': baseline_bits,
        'baseline_energy': float(original_energy[baseline_index].item()),
        'baseline_feasible': flags[baseline_index],
        'selected_stage': 'zero_objective' if zero_objective else ('simulated_bifurcation' if index < len(original) else 'tabu_refinement'),
        'selected_trial': (index % len(original)) // count,
        'selected_energy': float(energies[index].item()),
        'selected_feasible': flags[index],
        'refinement_steps': 0 if zero_objective else GPU_BUDGET['refinement']['steps'],
        'zero_objective_shortcut': zero_objective,
        'search_device': str(q.device),
        'timings_ms': {'sb_trials': trial_ms, 'refinement': refinement_ms,
                      'validation_and_selection': (time.perf_counter()-validation_started)*1000},
        'reference_answer_used': False,
    }
    return selected, energies[index], metadata
