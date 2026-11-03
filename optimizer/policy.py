"""One disclosed solver budget shared by the gateway and GPU worker."""

GPU_BUDGET = {
    'policy_version': 'general-quality-v1',
    'agents_per_trial': 128, 'steps_per_trial': 2000,
    'trials': [{'mode': 'ballistic', 'heated': False, 'seed_offset': 0},
               {'mode': 'discrete', 'heated': True, 'seed_offset': 104729}],
    'early_stopping': False,
    'refinement': {'method': 'tabu_one_two_bit', 'steps': 128,
                   'incumbents_retained': True, 'dtype': 'float64'},
    'candidate_selection': 'feasible_first_then_original_energy_float64',
    'original_candidates_retained': True,
    'reference_answer_used': False, 'model_answer_repair': False,
}
