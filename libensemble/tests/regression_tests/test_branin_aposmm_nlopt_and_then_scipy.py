# """
# Runs libEnsemble on a branin calculation with aposmm/nlopt.
#
# Execute via one of the following commands (e.g. 3 workers):
#    mpiexec -np 4 python3 test_branin_aposmm_nlopt_and_then_scipy.py
#
# The number of concurrent evaluations of the objective function will be 4-1=3.
# """

# Do not change these lines - they are parsed by run-tests.sh
# TESTSUITE_COMMS: mpi
# TESTSUITE_NPROCS: 2 4

import sys
import numpy as np
from copy import deepcopy
import pkg_resources

# Import libEnsemble items for this test
from libensemble.libE import libE
from libensemble.sim_funcs.branin.branin_obj import call_branin as sim_f
from libensemble.gen_funcs.aposmm import aposmm_logic as gen_f
from libensemble.tests.regression_tests.support import persis_info_2 as persis_info, aposmm_gen_out as gen_out, branin_vals_and_minima as M
from libensemble.tests.regression_tests.common import parse_args, save_libE_output, per_worker_stream

nworkers, is_master, libE_specs, _ = parse_args()

if libE_specs['comms'] == 'tcp':
    sys.exit("Cannot run with tcp when repeated calls to libE -- aborting...")

sim_specs = {'sim_f': sim_f,
             'in': ['x'],
             'out': [('f', float)],
             'sim_dir': pkg_resources.resource_filename('libensemble.sim_funcs.branin', ''),  # to be copied by each worker
             'clean_jobs': True}

if nworkers == 1:
    # Have the workers put their directories in a different (e.g., a faster
    # /sandbox/ or /scratch/ directory)
    # Otherwise, will just copy in same directory as sim_dir
    sim_specs['sim_dir_prefix'] = '~'
elif nworkers == 3:
    sim_specs['uniform_random_pause_ub'] = 0.05

n = 2
gen_out += [('x', float, n), ('x_on_cube', float, n)]
gen_specs = {'gen_f': gen_f,
             'in': [o[0] for o in gen_out] + ['f', 'returned'],
             'out': gen_out,
             'num_active_gens': 1,
             'batch_mode': True,
             'lb': np.array([-5, 0]),
             'ub': np.array([10, 15]),
             'initial_sample_size': 20,
             'localopt_method': 'LN_BOBYQA',
             'dist_to_bound_multiple': 0.99,
             'xtol_rel': 1e-3,
             'min_batch_size': nworkers,
             'high_priority_to_best_localopt_runs': True,
             'max_active_runs': 3}

persis_info = per_worker_stream(persis_info, nworkers + 1)
persis_info_safe = deepcopy(persis_info)

# Tell libEnsemble when to stop (stop_val key must be in H)
exit_criteria = {'sim_max': 150,
                 'elapsed_wallclock_time': 100,
                 'stop_val': ('f', -1)}

# Perform the run
for run in range(2):
    if run == 1:
        gen_specs['localopt_method'] = 'scipy_COBYLA'
        gen_specs.pop('xtol_rel')
        gen_specs['tol'] = 1e-5
        exit_criteria['sim_max'] = 500
        persis_info = deepcopy(persis_info_safe)

    H, persis_info, flag = libE(sim_specs, gen_specs, exit_criteria,
                                persis_info, libE_specs=libE_specs)

    if is_master:
        M = M[M[:, -1].argsort()]  # Sort by function values (last column)
        k = M.shape[0]
        tol = 1e-5
        for i in range(k):
            dist = np.min(np.sum((H['x'][H['local_min']]-M[i, :2])**2, 1))
            print(dist)
            assert dist < tol

        print("\nAPOSMM + " + gen_specs['localopt_method'] + " found " + str(k) + " minima to tolerance " + str(tol))
        save_libE_output(H, persis_info, __file__, nworkers)
