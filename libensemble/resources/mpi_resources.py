"""
Manages libensemble resources related to MPI tasks launched from nodes.
"""

import os
import logging
import subprocess


class MPIResourcesException(Exception):
    "Resources module exception."


def rassert(test, *args):
    if not test:
        raise MPIResourcesException(*args)


logger = logging.getLogger(__name__)
# To change logging level for just this module
# logger.setLevel(logging.DEBUG)


def get_MPI_runner():
    """ Return whether ``mpirun`` is openmpi or mpich """
    var = get_MPI_variant()
    if var in ['mpich', 'openmpi']:
        return 'mpirun'
    else:
        return var


def get_MPI_variant():
    """Returns MPI base implementation

    Returns
    -------
    mpi_variant: string:
        MPI variant 'aprun' or 'jsrun' or 'mpich' or 'openmpi' or 'srun'

    """

    try:
        subprocess.check_call(['aprun', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return 'aprun'
    except OSError:
        pass

    try:
        subprocess.check_call(['jsrun', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return 'jsrun'
    except OSError:
        pass

    try:
        # Explore mpi4py.MPI.get_vendor() and mpi4py.MPI.Get_library_version() for mpi4py
        try_mpich = subprocess.Popen(['mpirun', '-npernode'], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        stdout, _ = try_mpich.communicate()
        if 'unrecognized argument npernode' in stdout.decode():
            return 'mpich'
        return 'openmpi'
    except Exception:
        pass

    try:
        subprocess.check_call(['srun', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return 'srun'
    except OSError:
        pass


def task_partition(num_procs, num_nodes, procs_per_node, machinefile=None):
    """Takes provided nprocs/nodes/ranks and outputs working
    configuration of procs/nodes/ranks or error
    """

    # Convert to int if string is provided
    num_procs = int(num_procs) if num_procs else None
    num_nodes = int(num_nodes) if num_nodes else None
    procs_per_node = int(procs_per_node) if procs_per_node else None

    # If machinefile is provided - ignore everything else
    if machinefile:
        if num_procs or num_nodes or procs_per_node:
            logger.warning("Machinefile provided - overriding "
                           "procs/nodes/procs_per_node")
        return None, None, None

    if not num_procs:
        rassert(num_nodes and procs_per_node,
                "Need num_procs, num_nodes/procs_per_node, or machinefile")
        num_procs = num_nodes * procs_per_node

    elif not num_nodes:
        procs_per_node = procs_per_node or num_procs
        num_nodes = num_procs//procs_per_node

    elif not procs_per_node:
        procs_per_node = num_procs//num_nodes

    rassert(num_procs == num_nodes*procs_per_node,
            "num_procs does not equal num_nodes*procs_per_node")
    return num_procs, num_nodes, procs_per_node


def _max_rsets_per_node(worker_resources):
    """ Return the maximum rsets per node for any node on this worker"""
    # SH TODO: Need to add tests that go across the uneven nodes.
    rset_team = worker_resources.rset_team
    local_rsets_list = worker_resources.local_rsets_list
    rsets_on_node = [local_rsets_list[rset] for rset in rset_team]
    return max(rsets_on_node)


def get_resources(resources, num_procs=None, num_nodes=None,
                  procs_per_node=None, hyperthreads=False):
    """Reconciles user-supplied options with available worker
    resources to produce run configuration.

    Detects resources available to worker, checks whether an existing
    user-supplied config is valid, and fills in any missing config
    information (i.e., num_procs/num_nodes/procs_per_node)

    User-supplied config options are honored, and an exception is
    raised if these are infeasible.
    """
    wresources = resources.worker_resources
    gresources = resources.glob_resources
    node_list = wresources.local_nodelist
    rassert(node_list, "Node list is empty - aborting")
    local_node_count = wresources.local_node_count

    cores_avail_per_node = \
        (gresources.logical_cores_avail_per_node if hyperthreads else
         gresources.physical_cores_avail_per_node)

    rsets_per_node = _max_rsets_per_node(wresources)

    # SH TODO: Evaluate situation when one rset is > 1 node.
    #          Consider - may still be better to use best_split and construct.
    # Advantage of cores per rset first is they will always get same no. per rset (double  rsets, double cores)
    # Advantage of multiply first is less wasted cores.
    cores_avail_per_node_per_worker = cores_avail_per_node//rsets_per_node * wresources.slot_count
    # cores_avail_per_node_per_worker = int(cores_avail_per_node/rsets_per_node * wresources.slot_count)

    # SH TODO:This is when slots could be used to create a machinefile
    #         constrained by any options (num_nodes etc) they have entered.
    rassert(wresources.even_slots,
            "Uneven distribution of node resources not yet supported. Nodes and slots are: {}"
            .format(wresources.slots))

    if not num_procs and not procs_per_node:
        rassert(cores_avail_per_node_per_worker > 0,
                "There is less than one core per resource set. "
                "Provide num_procs or num_nodes/procs_per_node to oversubsribe")
        procs_per_node = cores_avail_per_node_per_worker
        if not num_nodes:
            # If no decomposition supplied - use all available cores/nodes
            num_nodes = local_node_count
            logger.debug("No decomposition supplied - "
                         "using all available resource. "
                         "Nodes: {}  procs_per_node {}".
                         format(num_nodes, procs_per_node))
    elif not num_nodes and not procs_per_node:
        if num_procs <= cores_avail_per_node_per_worker:
            num_nodes = 1
        else:
            num_nodes = local_node_count
    elif not num_procs and not num_nodes:
        num_nodes = local_node_count

    # Checks config is consistent and sufficient to express
    num_procs, num_nodes, procs_per_node = \
        task_partition(num_procs, num_nodes, procs_per_node)

    # print('cores per rset {}.  slot count {}  procs_per_node {}'.\
    # format(cores_avail_per_node_per_rset, wresources.slot_count, procs_per_node),flush=True)

    rassert(num_nodes <= local_node_count,
            "Not enough nodes to honor arguments. "
            "Requested {}. Only {} available".
            format(num_nodes, local_node_count))

    if gresources.enforce_worker_core_bounds:
        rassert(procs_per_node <= cores_avail_per_node,
                "Not enough processors on a node to honor arguments. "
                "Requested {}. Only {} available".
                format(procs_per_node, cores_avail_per_node))

        rassert(procs_per_node <= cores_avail_per_node_per_worker,
                "Not enough processors per worker to honor arguments. "
                "Requested {}. Only {} available".
                format(procs_per_node, cores_avail_per_node_per_worker))

        rassert(num_procs <= (cores_avail_per_node * local_node_count),
                "Not enough procs to honor arguments. "
                "Requested {}. Only {} available".
                format(num_procs, cores_avail_per_node*local_node_count))

    if num_nodes < local_node_count:
        logger.warning("User constraints mean fewer nodes being used "
                       "than available. {} nodes used. {} nodes available".
                       format(num_nodes, local_node_count))

    return num_procs, num_nodes, procs_per_node


def create_machinefile(resources, machinefile=None, num_procs=None,
                       num_nodes=None, procs_per_node=None,
                       hyperthreads=False):
    """Creates a machinefile based on user-supplied config options,
    completed by detected machine resources
    """

    machinefile = machinefile or 'machinefile'
    if os.path.isfile(machinefile):
        try:
            os.remove(machinefile)
        except Exception as e:
            logger.warning("Could not remove existing machinefile: {}".format(e))

    node_list = resources.worker_resources.local_nodelist
    logger.debug("Creating machinefile with {} nodes and {} ranks per node".
                 format(num_nodes, procs_per_node))

    with open(machinefile, 'w') as f:
        for node in node_list[:num_nodes]:
            f.write((node + '\n') * procs_per_node)

    built_mfile = (os.path.isfile(machinefile)
                   and os.path.getsize(machinefile) > 0)
    return built_mfile, num_procs, num_nodes, procs_per_node


def get_hostlist(resources, num_nodes=None):
    """Creates a hostlist based on user-supplied config options.

    completed by detected machine resources
    """
    node_list = resources.worker_resources.local_nodelist
    hostlist_str = ",".join([str(x) for x in node_list[:num_nodes]])
    return hostlist_str
