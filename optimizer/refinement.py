"""Bounded, batched QUBO tabu search. Works only from Q and SB candidates.

No problem-family rules, source CSV, reference optimum or other model answer
enters this search. CUDA is enforced by the production caller.
"""
import torch


def energy(q, x, offset):
    return ((x @ q) * x).sum(dim=1) + offset


def refine(q, candidates, offset, *, steps=128):
    """Explore one/two-bit moves, retaining the best visited vector per agent.

    Tabu tenure discourages immediate reversals; aspiration allows a tabu move
    when it beats that agent's incumbent. All objectives are recomputed using
    the original float64 matrix. Incumbents include the supplied SB candidates.
    """
    if q.dtype != torch.float64 or q.device != candidates.device:
        raise ValueError('invalid_refinement_inputs')
    x = candidates.to(torch.float64).clone()
    count, n = x.shape
    incumbent = x.clone()
    best = energy(q, x, offset)
    current = best.clone()
    # This formula also handles a nonsymmetric Q without altering x.T Q x.
    symmetric_sum = q + q.T
    diagonal = q.diagonal()
    tabu_until = torch.zeros((count, n), dtype=torch.int64, device=q.device)
    agents = torch.arange(count, device=q.device)
    tenure_base = min(max(1, n // 8), max(1, n - 1))
    tenure_spread = max(1, min(5, n - tenure_base))
    pair_i, pair_j = torch.triu_indices(n, n, offset=1, device=q.device)
    indices = torch.arange(n, device=q.device)
    move_i = torch.cat([indices, pair_i])
    move_j = torch.cat([indices, pair_j])
    interaction = symmetric_sum[pair_i, pair_j]
    for step in range(steps):
        direction = 1 - 2*x
        single = direction*(x @ symmetric_sum) + diagonal
        pair = single[:, pair_i] + single[:, pair_j] + direction[:, pair_i]*direction[:, pair_j]*interaction
        delta = torch.cat([single, pair], dim=1)
        expiry = torch.cat([tabu_until, torch.maximum(tabu_until[:, pair_i], tabu_until[:, pair_j])], dim=1)
        aspiration = current[:, None] + delta < best[:, None] - 1e-9
        eligible = (expiry <= step) | aspiration
        scores = torch.where(eligible, delta, float('inf'))
        # For very small n all moves can be tabu. Release the oldest one.
        exhausted = ~eligible.any(dim=1)
        oldest = expiry.argmin(dim=1)
        scores[agents, oldest] = torch.where(exhausted, delta[agents, oldest], scores[agents, oldest])
        chosen = scores.argmin(dim=1)
        i, j = move_i[chosen], move_j[chosen]
        x[agents, i] = 1-x[agents, i]
        x[agents, j] = torch.where(chosen >= n, 1-x[agents, j], x[agents, j])
        tenure = tenure_base + (agents + step) % tenure_spread
        tabu_until[agents, i] = step + tenure + 1
        tabu_until[agents, j] = step + tenure + 1
        current = energy(q, x, offset)
        improved = current < best - 1e-9
        incumbent = torch.where(improved[:, None], x, incumbent)
        best = torch.where(improved, current, best)
    return incumbent, best
