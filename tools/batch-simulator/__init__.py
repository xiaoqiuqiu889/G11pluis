"""batch-simulator — N synthetic plays of a scene contract.

Public surface:
    simulator.simulate_one(contract, policy, seed)  — one play
    simulator.simulate_batch(contract, policy, n)   — N plays + stats
    simulator.POLICIES                              — {'random','heuristic','ai'}
    simulator.main(argv)                            — CLI entrypoint
"""
