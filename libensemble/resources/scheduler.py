import copy
import numpy as np
from libensemble.resources.resources import Resources  # SH TODO: Consider pass resources via libE_info to alloc.


class ResourceSchedulerException(Exception):
    "Raised for any exception in the alloc support"


class ResourceScheduler:

    def __init__(self, user_resources=None, sched_opts={}):
        self.resources = user_resources or Resources.resources.managerworker_resources
        self.rsets_free = self.resources.rsets_free
        self.avail_rsets_by_group = None  #could set here - but might save time not doing so if not used.

        # Process scheduler options
        # Split across more nodes if space not currently avail (even though can fit when free).
        self.split2fit = sched_opts.get('split2fit', True)

    # SH TODO: Look at dealing with this more efficently - being able to store sructures.
    def assign_resources(self, rsets_req):
        """Schedule resource sets to a work item if possible and assign to worker

        If the resources required are less than one node, they will be
        allocated to the smallest available sufficient slot.

        If the resources required are more than one node, then enough
        full nodes will be allocated to cover the requirement.

        The assigned resources are marked directly in the resources module.

        Returns a list of resource sets ids. A return of None implies
        insufficient resources.
        """

        if rsets_req > self.resources.num_rsets:
            raise ResourceSchedulerException("More resource sets requested {} than exist {}"
                                             .format(rsets_req, self.resources.num_rsets))

        # Check total number rsets available
        if rsets_req > self.rsets_free:  # A local rsets_free....
            return None

        num_groups = self.resources.num_groups
        max_grpsize = self.resources.rsets_per_node  #assumes even

        avail_rsets_by_group = self.get_avail_rsets_by_group()
        print('\nChecking ------ avail_rsets_by_group before {} rsets_req {} rsets free {}'.format(self.avail_rsets_by_group, rsets_req, self.rsets_free))

        #Maybe more efficient way than making copy_back
        tmp_avail_rsets_by_group = copy.deepcopy(avail_rsets_by_group)

        # print('Available rsets_by_group:', avail_rsets_by_group)  # SH TODO: Remove

        # SH TODO: Review scheduling > 1 node strategy
        # Currently tries for even split and if cannot, then rounds rset up to full nodes.
        # Log if change requested to make fit/round up - at least at debug level.
        # preferable to set a calc_groups function once and can use with in a loop to try different splits

        # Work out best target fit - if all rsets were free.
        rsets_req, num_groups_req, rsets_req_per_group = \
            self.calc_req_split(rsets_req, max_grpsize, num_groups, extend=True)

        if self.split2fit:
            sorted_lengths = ResourceScheduler.get_sorted_lens(avail_rsets_by_group)
            max_even_grpsize = sorted_lengths[num_groups_req - 1]
            if max_even_grpsize == 0 and rsets_req > 0:
                return None
            if max_even_grpsize < rsets_req_per_group:
                # Cannot fit in smallest number of nodes - try to split
                rsets_req, num_groups_req, rsets_req_per_group = \
                    self.calc_even_split_uneven_groups(max_even_grpsize, num_groups_req, rsets_req, sorted_lengths, num_groups, extend=False)

                # SH TODO: Maybe make this a try/except rather than return none if cant find a partition.
                if rsets_req is None:
                    return None
                #rsets_req, num_groups_req, rsets_req_per_group = \
                    #self.calc_req_split(rsets_req, max_even_grpsize, num_groups, extend=False)
        #else:
            #max_even_grpsize = max_grpsize


        print('max_grpsize is', max_grpsize)
        if max_grpsize is not None:
            max_upper_bound = max_grpsize + 1
            print('max_upper_bound', max_upper_bound)
        else:
            # All in group zero
            if len(tmp_avail_rsets_by_group) > 1:
                raise AllocException("There should only be one group if resources is not set")
            max_upper_bound = len(tmp_avail_rsets_by_group[0]) + 1

        # Now find slots on as many nodes as need
        accum_team = []
        group_list = []
        print('\nLooking for {} rsets'.format(rsets_req))

        for ng in range(num_groups_req):
            print(' - Looking for group {} out of {}: Groupsize {}'.format(ng+1, num_groups_req, rsets_req_per_group))
            cand_team, cand_group = \
                self.find_candidate(tmp_avail_rsets_by_group, group_list, rsets_req_per_group, max_upper_bound)

            if cand_group is not None:
                accum_team.extend(cand_team)
                group_list.append(cand_group)

                print('      here b4:  group {} avail {} - cand_team {}'.format(group_list, tmp_avail_rsets_by_group, cand_team))
                for rset in cand_team:
                    tmp_avail_rsets_by_group[cand_group].remove(rset)
                print('      here aft: group {} avail {}'.format(group_list, tmp_avail_rsets_by_group))

        print('Found rset team {} - group_list {}'.format(accum_team, group_list))
        #import pdb;pdb.set_trace()

        if len(accum_team) == rsets_req:
            # A successful team found
            rset_team = sorted(accum_team)
            print('Setting rset team {} - group_list {}'.format(accum_team, group_list))
            self.avail_rsets_by_group = tmp_avail_rsets_by_group #maybe use function to update
            self.rsets_free -= rsets_req
            print('avail_rsets_by_group after', self.avail_rsets_by_group)
        else:
            rset_team = None  # Insufficient resources to honor
            print('------Could not find enough rsets - returning None-------')

        # print('Assigned rset team {} to worker {}'.format(rset_team,worker_id))  # SH TODO: Remove
        return rset_team


    def find_candidate(self, rsets_by_group, group_list, rsets_req_per_group, max_upper_bound):
        """Find a candidate slot in a group"""
        cand_team = []
        cand_group = None
        upper_bound = max_upper_bound
        for g in rsets_by_group:
            print('   -- Search possible group {} in {}'.format(g, rsets_by_group))
            if g in group_list:
                continue
            nslots = len(rsets_by_group[g])
            if nslots == rsets_req_per_group:  # Exact fit.  # If make array - could work with different sized group requirements.
                cand_team = rsets_by_group[g].copy()  # SH TODO: check do I still need copy - given extend below?
                cand_group = g
                break  # break out inner loop...
            elif rsets_req_per_group < nslots < upper_bound:
                cand_team = rsets_by_group[g][:rsets_req_per_group]
                cand_group = g
                upper_bound = nslots
        return cand_team, cand_group


    # Also could follow my other approaches and make static and pass resources (can help with testing)
    # SH TODO: An alt. could be to return an object
    #          When merge CWP branch - will need option to use active receive worker
    def get_avail_rsets_by_group(self):
        """Return a dictionary of resource set IDs for each group (e.g. node)

        If groups are not set they will all be in one group (group 0)

        E.g: Say 8 resource sets / 2 nodes
        GROUP  1: [1,2,3,4]
        GROUP  2: [5,6,7,8]
        """
        if self.avail_rsets_by_group is None:
            rsets = self.resources.rsets
            groups = np.unique(rsets['group'])
            self.avail_rsets_by_group = {}
            for g in groups:
                self.avail_rsets_by_group[g] = []
            for ind, rset in enumerate(rsets):
                if not rset['assigned']:
                    g = rset['group']
                    self.avail_rsets_by_group[g].append(ind)
        return self.avail_rsets_by_group


    def calc_req_split(self,rsets_req, max_grpsize, num_groups, extend):
        if self.resources.even_groups:  # This is total group sizes even (not available sizes)
            rsets_req, num_groups_req, rsets_req_per_group = \
                self.calc_rsets_even_grps(rsets_req, max_grpsize, num_groups, extend)
        else:
            print('Warning: uneven groups - but using even groups function')
            rsets_req, num_groups_req, rsets_req_per_group = \
                self.calc_rsets_even_grps(rsets_req, max_grpsize, num_groups, extend)
        return rsets_req, num_groups_req, rsets_req_per_group


    # SH TODO: This will be special case of calc_req_uneven_split
    def calc_rsets_even_grps(self, rsets_req, max_grpsize, max_groups, extend):
        """Calculate an even breakdown to best fit rsets_req input"""

        if rsets_req == 0:
            return 0, 0, 0

        num_groups_req = rsets_req//max_grpsize + (rsets_req % max_grpsize > 0)  # Divide with roundup.

        # Up to max groups - keep trying for an even split
        if num_groups_req > 1:
            even_partition = False
            tmp_num_groups = num_groups_req
            while tmp_num_groups <= max_groups:
                if rsets_req % tmp_num_groups == 0:
                    even_partition = True
                    break
                tmp_num_groups += 1

            if even_partition:
                num_groups_req = tmp_num_groups
                rsets_req_per_group = rsets_req//num_groups_req  # This should always divide perfectly.
            else:
                if extend:
                    rsets_req_per_group = rsets_req//num_groups_req + (rsets_req % num_groups_req > 0)
                    rsets_req = num_groups_req * rsets_req_per_group
                    # SH TODO log here (atleast in debug)
                    print('Warning: Increasing resource requirement to obtain an even partition of resource sets'
                        'to nodes. rsets_req {}  num_groups_req {} rsets_req_per_group {}'.
                        format(rsets_req, num_groups_req, rsets_req_per_group))
                else:
                    rsets_req_per_group = max_grpsize

        else:
            rsets_req_per_group = rsets_req

        return rsets_req, num_groups_req, rsets_req_per_group


    # SH TODO: May be able to use an equivalent of this for when have uneven groups to start with.
    def calc_even_split_uneven_groups(self, rsets_req_per_group, num_groups_req, rsets_req, sorted_lens, max_groups, extend):
        """Calculate an even breakdown to best fit rsets_req with uneven groups"""
        if rsets_req == 0:
            return 0, 0, 0

        ngroups = num_groups_req
        while rsets_req_per_group * ngroups != rsets_req:
            if rsets_req_per_group * ngroups > rsets_req:
                rsets_req_per_group -= 1
            else:
                ngroups += 1
                if ngroups > max_groups:
                    return None, None, None  # No split found
                rsets_req_per_group = sorted_lens[ngroups -1]

        # SH TODO: Could add extend option here - then sending back rsets_req will make sense.
        return rsets_req, ngroups, rsets_req_per_group



    @staticmethod
    def get_max_len(avail_rsets, num_groups):
        """Get max length of a list value in a dictionary"""
        # SH TODO: Requires a sort - could use this sorted list iteratively to find min slots...
        lengths = sorted([len(v) for v in avail_rsets.values()], reverse=True)
        return lengths[num_groups - 1]

    @staticmethod
    def get_sorted_lens(avail_rsets):
        """Get max length of a list value in a dictionary"""
        # SH TODO: Requires a sort - could use this sorted list iteratively to find min slots...
        return sorted([len(v) for v in avail_rsets.values()], reverse=True)

class UnevenResourceScheduler(ResourceScheduler):

    def assign_resources(rsets_req, worker_id, user_resources=None):
        pass
