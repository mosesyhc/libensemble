import matplotlib.pyplot as plt
import numpy as np
from gen import gen_random_sample
from sim import sim_find_sine

from libensemble import Ensemble
from libensemble.specs import ExitCriteria, GenSpecs, LibeSpecs, SimSpecs

if __name__ == "__main__":  # Python-quirk required on macOS and windows
    libE_specs = LibeSpecs(nworkers=4, comms="local")

    gen_specs = GenSpecs(
        gen_f=gen_random_sample,  # Our generator function
        out=[("x", float, (1,))],  # gen_f output (name, type, size)
        user={
            "lower": np.array([-3]),  # lower boundary for random sampling
            "upper": np.array([3]),  # upper boundary for random sampling
            "gen_batch_size": 5,  # number of x's gen_f generates per call
        },
    )

    sim_specs = SimSpecs(
        sim_f=sim_find_sine,  # Our simulator function
        inputs=["x"],  # Input field names. "x" from gen_f output
        out=[("y", float)],  # sim_f output. "y" = sine("x")
    )

    exit_criteria = ExitCriteria(sim_max=80)  # Stop libEnsemble after 80 simulations

    ensemble = Ensemble(sim_specs, gen_specs, exit_criteria, libE_specs)
    ensemble.add_random_streams()  # setup the random streams unique to each worker
    ensemble.run()  # start the ensemble. Blocks until completion.

    history = ensemble.H  # start visualizing our results

    colors = ["b", "g", "r", "y", "m", "c", "k", "w"]

    for i in range(1, libE_specs.nworkers + 1):
        worker_xy = np.extract(history["sim_worker"] == i, history)
        x = [entry.tolist()[0] for entry in worker_xy["x"]]
        y = [entry for entry in worker_xy["y"]]
        plt.scatter(x, y, label="Worker {}".format(i), c=colors[i - 1])

    plt.title("Sine calculations for a uniformly sampled random distribution")
    plt.xlabel("x")
    plt.ylabel("sine(x)")
    plt.legend(loc="lower right")
    plt.savefig("tutorial_sines.png")
