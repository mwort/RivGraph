# -*- coding: utf-8 -*-
"""
Skeleton Walking Utils (walk.py)
================================
Functions for walking along skeletons and finding branchpoints.

Created on Mon Sep 10 09:39:19 2018
"""
import numpy as np
from skimage import measure
from scipy import stats
import rivgraph.im_utils as iu
import rivgraph.ln_utils as lnu


def handle_bp(linkid, bpnode, nodes, links, links2do, Iskel):
    """
    Handle branchpoints.

    When walking along a skeleton and encountering a branchpoint, we want to
    initialize all un-done links emanating from the branchpoint. Each new link
    contains the branchpoint as the first index, and this function also takes
    the first step of the link.

    Parameters
    ----------
    linkid : int
        Link id of the link walking from.
    bpnode : np.int
        Node id of the branchpoint to be resolved.
    nodes : dict
        Network nodes and associated properties.
    links : dict
        Network links and associated properties.
    links2do : OrderedSet
        This set keeps track of all the links that still need to be resolved
        in the full skeleton. It is generated and populated in mask_to_graph.
    Iskel : np.ndarray
        Image of the local skeletonized mask.

    Returns
    -------
    links : TYPE
        Network links and associated properties with the branchpoint links
        added.
    nodes : TYPE
        Network nodes and associated properties with the branchpoint-related
        nodes added.
    links2do : OrderedSet
        Same as input, but with new link emanators added and linkid removed.

    """
    links2do.remove(linkid)

    # If the branchpoint has already been visited, we don't need to
    # re-initialize emanating links
    if bpnode in nodes['idx']:
        doneflag = 1
    else:
        doneflag = 0

    linkidx = links['id'].index(linkid)

    # Add the branchpoint to nodes dict
    nodes = lnu.node_updater(nodes, bpnode, linkid)

    # Update link connectivity
    links = lnu.link_updater(links, linkid, conn=nodes['idx'].index(bpnode))

    if doneflag == 1:
        return links, nodes, links2do

    # We must initialize new branchpoints. If branchpoints are connected,
    # their links must be assigned to preserve 4-connectivity to avoid
    # problems when walking.

    # Resolve the branchpoint cluster (or single branchpoint)
    bp = bp_cluster([bpnode], Iskel)

    # Find the pixels emanating from the cluster
    emanators = np.array(list(find_emanators(bpnode, Iskel) - set(bp) -
                              set(links['idx'][linkidx])))

    # For each branchpoint, separate emanators into 4-connected neighbors and
    # diagonally-connected neighbors
    fourconn = []
    emremove = []
    for b in bp:
        abdif = abs(b-emanators)
        for i, a in enumerate(abdif):
            if a == 1 or a == Iskel.shape[1]:
                fourconn.append([b, emanators[i]])
                emremove.append(emanators[i])
    # Remove the 4-connected emanators we've just assigned from emanators list
    emanators = np.array([e for e in emanators if e not in emremove])

    # Make diagonal links
    diagconn = []
    for b in bp:
        abdif = abs(b-emanators)
        for i, a in enumerate(abdif):
            if a == Iskel.shape[1] + 1 or a == Iskel.shape[1] - 1:
                diagconn.append([b, emanators[i]])

    # Make links connecting adjacent branchpoints
    bp_pairs = []
    for b in bp:
        bn = walkable_neighbors([b], Iskel)
        for bb in bp:
            if bb in bn:
                bp_pairs.append(set([b, bb]))

    # Get the unique links - ordering is lost
    bp_pairs = [list(i) for i in set(tuple(i) for i in bp_pairs)]

    # Update links and nodes
    # Create links between adjacent branchpoints
    for b in bp_pairs:
        linkid = max(links['id']) + 1
        nodes = lnu.node_updater(nodes, b[0], linkid)
        nodes = lnu.node_updater(nodes, b[1], linkid)
        links = lnu.link_updater(links, linkid, b,
                                 conn=nodes['idx'].index(b[0]))
        links = lnu.link_updater(links, linkid, conn=nodes['idx'].index(b[1]))

    # Finally, initialize new links to be walked
    # Before issuing new links, ensure that the link has not
    # already been walked

    # Initialize the fourconn first so they will be walked first
    for p in fourconn:
        # Check if link to issue has already been resolved
        nodeidx = nodes['idx'].index(p[0])
        donelinks = nodes['conn'][nodeidx]
        isdone = 0
        for dl in donelinks:
            if set(links['idx'][links['id'].index(dl)][-2:]) == set(p):
                isdone = 1
        if isdone == 0:
            linkid = max(links['id']) + 1
            links2do.add(linkid)
            nodes = lnu.node_updater(nodes, p[0], linkid)
            links = lnu.link_updater(links, linkid, p,
                                     nodes['idx'].index(p[0]))

    # Then initialize the diagonals
    for p in diagconn:
        # Check if link to issue has already been resolved
        nodeidx = nodes['idx'].index(p[0])
        donelinks = nodes['conn'][nodeidx]
        isdone = 0
        for dl in donelinks:
            if set(links['idx'][links['id'].index(dl)][-2:]) == set(p):
                isdone = 1
        if isdone == 0:
            linkid = max(links['id']) + 1
            links2do.add(linkid)
            nodes = lnu.node_updater(nodes, p[0], linkid)
            links = lnu.link_updater(links, linkid, p,
                                     nodes['idx'].index(p[0]))

    return links, nodes, links2do


def bp_cluster(bp, Iskel):
    """
    Find clusters of branchpoints.

    Finds clusters of branchpoints; i.e. branchpoints that are immediately
    adjacent to each other in an 8-connected sense. This function is self-
    referential in order to find all neighboring branchpoints.

    Parameters
    ----------
    bp : list
        Contains the branchpoint cluster as indices (np.ravel_multi_index)
        within Iskel. In the initial call, this list contains only a single
        branchpoint.
    Iskel : np.ndarray
        Image of the skeletonized mask.

    Returns
    -------
    bp : list
        Contains the branchpoint cluster as indices (np.ravel_multi_index)
        within Iskel.

    """
    bp_neighs = walkable_neighbors(bp, Iskel)
    while bp_neighs:
        b = bp_neighs.pop()
        if is_bp(b, Iskel) == 1:
            if b not in bp:
                bp.extend([b])
                bp_cluster(bp, Iskel)

    return bp


def idcs_no_turnaround(idcs, Iskel):
    """
    Find possible indices to walk to given two input indices.

    Returns list of possible indices to walk toward given two input indices
    (idcs).

    Possible indices are defined as those which require no turning around;
    e.g. if moving down, only indices further below idcs[1] will be returned.
    Based on directionality, only three possible indices should be returned
    for all cases.

    Parameters
    ----------
    idcs : list
        Resolved indices within Iskel of the link, in order, for which the next
        step needs to be taken.
    Iskel : np.ndarray
        Image of the skeletonized mask.

    Returns
    -------
    poss_walk_idcs : list
        Indices within Iskel of possible next steps that ensure the walk will
        not move "backwards."

    """
    ncols = Iskel.shape[1]
    idxdif = idcs[0]-idcs[1]

    if idxdif == -ncols - 1:
        walkdirs = [1, ncols, ncols+1]
    elif idxdif == -ncols:
        walkdirs = [ncols-1, ncols, ncols+1]
    elif idxdif == -ncols + 1:
        walkdirs = [-1, ncols-1, ncols]
    elif idxdif == -1:
        walkdirs = [-ncols+1, 1, ncols+1]
    elif idxdif == 1:
        walkdirs = [-ncols-1, -1, -ncols-1]
    elif idxdif == ncols-1:
        walkdirs = [-ncols, -ncols+1, 1]
    elif idxdif == ncols:
        walkdirs = [-ncols-1, -ncols, -ncols+1]
    elif idxdif == ncols+1:
        walkdirs = [-1, -ncols-1, -ncols]

    poss_walk_idcs = [idcs[-1] + wd for wd in walkdirs]
    return poss_walk_idcs


def cant_walk(links, linkidx, nodes, Iskel):
    """
    Find pixels that cannot be walked to.

    Given an input link defined by linkidx, return all the pixels that cannot
    be walked to. These include:

    1. originating node (and any nodes adjacent to this one)

    2. emanating links (i.e. first pixel away from each node)

    3. links that have been resolved walking AWAY from the node (toward node not included)

    Parameters
    ----------
    links : dict
        Network links and associated properties.
    linkidx : int
        Index of the link id within links['id'] of the link to analyze.
    nodes : dict
        Network nodes and associated properties.
    Iskel : np.ndarray
        Image of the skeletonized mask.

    Returns
    -------
    walked : set
        Indices of pixels within Iskel that have already been walked to.

    """
    # 1. Originating node and its adjacent nodes
    bps = bp_cluster([links['idx'][linkidx][0]], Iskel)
    walked = set(bps)

    # 2. Emanating links
    for bp in bps:
        walked = walked | set(walkable_neighbors([bp], Iskel))

    # 3. Links walking away from node
    nodeidx = links['idx'][linkidx][0]
    connlinks = nodes['conn'][nodes['idx'].index(nodeidx)]

    for cl in connlinks:
        templinkidx = links['id'].index(cl)
        # If statement ensures we only consider links walked from the node
        # (as opposed to links entering the node)
        if links['idx'][templinkidx][0] == links['idx'][linkidx][0]:
            walked = walked | set(links['idx'][templinkidx][:-1])
        else:
            # Not sure the [1:] is necessary here...
            walked = walked | set(links['idx'][templinkidx][1:])

    return walked


def find_emanators(bpnode, Iskel):
    """
    Find possible next steps along the skeleton.

    Returns all possible next steps along the skeleton from a given pixel.
    Emanators are the second nodes in each link, or the first nodes away from
    the link endpoint.

    Parameters
    ----------
    bpnode : np.int
        Index within Iskel to look for emanators.
    Iskel : np.ndarray
        Image of the skeletonized mask.

    Returns
    -------
    all_emanators: set
        Indices within Iskel representing emanating nodes from bpnode.

    """
    # First, find all connected branchpoints
    branchpoints = bp_cluster([bpnode], Iskel)

    # Second, find the links emanating from these branchpoints
    emanators = set()
    for bp in branchpoints:
        emanators = emanators | set(walkable_neighbors([bp], Iskel))

    all_emanators = emanators - set(branchpoints)

    return all_emanators


def walkable_neighbors(link, Iskel):
    """
    Find all walkable neighbors from the end pixel of an input link.

    Returns all the walkable neighbors from the end pixel of an input link.
    Walkable neighbors are simply pixels that are "on" within Iskel. The pixels
    in the link are excluded as possibilities.

    Parameters
    ----------
    link : list
        Contains all the pixel indices within Iskel of the link to find
        walkable neighbors.
    Iskel : np.ndarray
        Image of the skeletonized mask.

    Returns
    -------
    neighs : set
        Indices within Iskel of neighboring pixels to walk to.

    """
    idx = link[-1]

    # Find its neighbors (next possible steps)
    neighs = set(get_neighbors(idx, Iskel))

    try:
        neighs = neighs - set(link[-2:])
    except Exception:
        pass

    return neighs


def get_neighbors(idx, Iskel):
    """
    Get a flattened array of neighboring pixel indices.

    Returns a flattened array of the neighboring pixel indices within Iskel
    that are True. Only looks at 8-connected neighbors (i.e. a 3x3 kernel with
    centered on idx).

    Parameters
    ----------
    idx : np.int
        Index within Iskel to get neighbors.
    Iskel : np.ndarray
        Image of the skeletonized mask, but can be any image array.

    Returns
    -------
    neighbor_idcs_gloal : list
        Indices within Iskel of True pixels bordering idx.

    """
    size = (3, 3)
    cent_idx = 4  # OR int((size[0]*size[1] - 1) / 2)

    # Pull square with idx at center
    I, row_offset, col_offset = iu.get_array(idx, Iskel, size)
    I_flat = np.ravel(I)

    # Find its neighbors (next possible steps)
    neighbor_idcs, _ = iu.neighbors_flat(cent_idx, I_flat, size[1])
    neighbor_idcs_gloal = iu.reglobalize_flat_idx(neighbor_idcs, size,
                                                  row_offset, col_offset,
                                                  Iskel.shape)

    return neighbor_idcs_gloal


def delete_link(linkid, links, nodes):
    """
    Delete a link from the links dictionary and update the nodes dictionary.

    Deletes a link from the links dictionary and updates the nodes dictionary
    to account for the deleted link. This is a special case of the delete_link
    found in ln_utils.py, as no properties have been added yet. It is possible
    that this function could be replaced by that one.

    Parameters
    ----------
    linkid : int
        Id of the link to delete.
    links : dict
        Network links and associated properties.
    nodes : dict
        Network nodes and associated properties.

    Returns
    -------
    links : dict
        Network links and associated properties with the link deleted.
    nodes : dict
        Network nodes and associated properties with the link deleted.

    """
    #TODO: Replace this function with the one in ln_utils.

    # Get index of link within links dict
    lid = links['id'].index(linkid)

    # Remove the link
    links['idx'].pop(lid)
    nodeidx = links['conn'].pop(lid)
    links['id'].remove(linkid)

    # Remove the link from node connectivity
    for ni in nodeidx:
        nodes['conn'][ni].remove(linkid)


    return links, nodes


def check_dup_links(linkid, links, nodes, links2do):
    """
    Check for duplicate links.

    Checks that the link represented by linkid has no dubplicates in the
    network. If so, the link is removed.

    Parameters
    ----------
    linkid : int
        Id of the link to check for duplication.
    links : dict
        Network links and associated properties.
    nodes : dict
        Network nodes and associated properties.
    links2do : OrderedSet
        This set keeps track of all the links that still need to be resolved
        in the full skeleton. It is generated and populated in
        :mod:`mask_to_graph`.

    Returns
    -------
    links : dict
        Network links and associated properties with duplicate link removed, if
        it existed.
    nodes : dict
        Network nodes and associated properties with duplicate ilnk removed, if
        it existed.
    links2do : OrderedSet
        This set keeps track of all the links that still need to be resolved
        in the full skeleton. It is generated and populated in
        :mod:`mask_to_graph`.
        The duplicate link, if found, is removed from this set.

    """
    linkidx = links['id'].index(linkid)

    link = links['idx'][linkidx]

    # Get index of node we are connecting to
    lconn = links['conn'][linkidx][1]

    # Get links that are connected to this node (set is required so we create
    # a copy rather than a view)
    # The set also ensure uniqueness, so if there is a loop at this node
    # it is only checked once for duplication
    nconn = set(nodes['conn'][lconn])

    # We don't want to check the link we're on; this also handles loops formed
    # by a link that starts and ends at the same node.
    nconn.remove(linkid)

    # Remove any duplicate links emanating from the node our link ends at
    for lid in nconn:
        if set(link[-2:]) == set(links['idx'][links['id'].index(lid)][:2]):
            # Keep the link we resolved, but delete the matching one
            links, nodes = delete_link(lid, links, nodes)
            try:
                links2do.remove(lid)
            except Exception:
                pass

    return links, nodes, links2do


def is_bp(idx, Iskel):
    """
    Determine if an index is a branchpoint.

    Determines if the index given by idx is a branchpoint. Branchpoints are
    not simply pixels in the skeleton with more than two neighbors; they are
    pruned through a somewhat complicated procedure that minimizes the number
    of required branchpoints to preserve the skeleton topology.

    Parameters
    ----------
    idx : np.int
        Index within Iskel to determine if it is a branchpoint.
    Iskel : np.ndarray
        Image of the skeletonized mask, but can be any image array.

    Returns
    -------
    isbp : int
        1 if idx is a branchpoint, else 0.

    """
    # TODO: change to return True/False rather than 1/0.
    # Trivial case, only one or two neighbors is not bp
    neighs = get_neighbors(idx, Iskel)
    if len(neighs) < 3:
        return 0

    # Pull out the neighborhood
    big_enough = 0
    size = (7, 7)

    # Loop to ensure the domain is large enough to capture all connected
    # nconn>2 pixels
    while big_enough == 0:
        centidx = (int((size[0]-1)/2), int((size[1]-1)/2))
        I, roffset, coffset = iu.get_array(idx, Iskel, size)

        # Find 4-connected pixels with connectivity > 2
        Ic = iu.im_connectivity(I)
        Ict = np.zeros_like(I)
        Ict[Ic > 2] = 1
        Ilab = measure.label(Ict, background=0, connectivity=1)

        cpy, cpx = np.where(Ilab == Ilab[centidx])
        big_enough = 1
        if 1 in cpx or size[0]-2 in cpx:
            size = (size[0] + 4, size[1])
            big_enough = 0
        if 1 in cpy or size[1]-2 in cpy:
            size = (size[0], size[1] + 4)
            big_enough = 0

    # Reduce image to subset of connected conn > 2 pixels with a 1 pixel
    # buffer by zeroing out values outside the domain
    I[:np.min(cpy)-1, :] = 0
    I[np.max(cpy)+2:, :] = 0
    I[:, :np.min(cpx) - 1] = 0
    I[:, np.max(cpx) + 2:] = 0

    # Take only the largest blob in case there are border stragglers
    I = iu.largest_blobs(I, 1, 'keep')

    # Zero out everything outside our region of interest
    Ic[np.bitwise_and(Ilab != Ilab[centidx], Ic > 2)] = 1  # set edge pixel connectivity to 1 (even if not true)
    Ic[I != 1] = 0

    # Trivial case where idx is the only possible branchpoint
    if np.sum(Ic > 2) == 1:
        return 1

    # Compute number of axes and four-connectivity
    Ina = naxes_connectivity(I)
    Inf = iu.nfour_connectivity(I)
    # Ravel everything
    Icr = np.ravel(Ic)
    Inar = np.ravel(Ina)
    Infr = np.ravel(Inf)

    bps = isbp_parsimonious(Ic, Icr, Inar, Infr)

    # Return branchpoints to global, flat coordinates
    bps = iu.reglobalize_flat_idx(bps, Ic.shape, roffset, coffset, Iskel.shape)

    # Check input idx for being a branchpoint
    if idx in bps:
        isbp = 1
    else:
        isbp = 0

    return isbp


def isbp_parsimonious(Ic, Icr, Inar, Infr):
    """
    Computes parsimonious set of branchpoints.

    Parameters
    ----------
    Ic : np.ndarray
        Image of possible branchpoints; values correspond to number of
        neighbors.
    Icr : np.ndarray
        Raveled (np.ravel) version of Ic.
    Inar : np.ndarray
        Raveled version of image returned by naxes_connectivity.
    Infr : np.ndarray
        Raveled version of image returned by nfour_connectivity.

    Returns
    -------
    bps : list
        All branchpoint indices within Ic.

    """
    # Find all possible branchpoints by considerng those with conn>2
    bp_poss = np.where(Ic > 2)
    bp_poss_i = np.ravel_multi_index(bp_poss, Ic.shape)
    bp_poss_i = list(set(bp_poss_i) - iu.edge_coords(Ic.shape))

    # Find all possible branchpoint combinations by walking from each
    # possible initial branchpoint
    bpsave = []
    for bpi in bp_poss_i:
        bptemp = isbp_walk_for_bps(np.array(Ic, dtype=bool), [bpi])
        bpsave.append(bptemp)

    # Number of branchpoints for each possible initial branchpoint
    bpcounts = [len(b) for b in bpsave]
    bpsolo = [bpsave[i].pop() for i, c in enumerate(bpcounts) if c == 1]

    # If only one branchpoint is required, use it. However, there could be
    # multiple branchpoints that can serve as the single; use the one with
    # highest naxes-connectivity; if there are still multiple choices, take the
    # highest 4-connectivity. If there are still no unique choices, choose the
    # highest 4-connected among the highest naxes-connected.
    if len(bpsolo) > 0:
        naxconn = Inar[bpsolo]
        maxnax = [bps for bps, nl in zip(bpsolo, naxconn) if nl == max(naxconn)]
        if len(maxnax) == 1:
            return [maxnax]
        else:
            fourconn = Infr[bpsolo]
            maxfour = [bpsolo[i] for i, fc in enumerate(fourconn) if fc == max(fourconn)]
            if len(maxfour) == 1:
                return [maxfour]
        # Now see if there's a max 4-conn within the max naxes-conn
        fourconn = Infr[maxnax]
        maxfour = [maxnax[i] for i, fc in enumerate(fourconn) if fc == max(fourconn)]
        return [min(maxfour)]

    # Set bp_must according to conn, naxes, nfour
    keepvals = [[6, 4, 2], [5, 3, 1], [5, 3, 4],
                [3, 3, 2], [3, 3, 1], [4, 2, 4]]
    bp_must = []
    for kv in keepvals:
        keeps = np.ndarray.tolist(np.where(np.logical_and(np.logical_and(Icr == kv[0], Inar == kv[1]), Infr == kv[2])==1)[0])
        bp_must = bp_must + keeps

    # Special cases - 4,4,2 - choose one
    keepvals = [[4, 4, 2]]
    for kv in keepvals:
        keeps = np.ndarray.tolist(np.where(np.logical_and(np.logical_and(Icr == kv[0], Inar == kv[1]), Infr == kv[2])==1)[0])
        if len(keeps) == 2:
            bp_must = bp_must + [keeps[0]]

    # Only consider combinations that have branchpoints where they must be placed
    if len(bp_must) > 0:
        bps = isbp_walk_for_bps(np.array(Ic, dtype=bool), bp_must)
        return bps

    # If there are no branchpoints that must exist based on patterns,
    # use the set with the smallest number of branchpoints. If there are multiple
    # sets, we move on...
    mincount = min(bpcounts)
    minidcs = [i for i, bpi in enumerate(bpcounts) if bpi == mincount]
    if len(minidcs) == 1:
        return bpsave[minidcs[0]]

    # Finally, choose branchpoints based on the most common branchpoints created
    # when walking from all possible branchpoints
    mode = stats.mode([p for b in bpsave for p in b])
    bp_init = np.ndarray.tolist(mode.mode)
    bps = isbp_walk_for_bps(np.array(Ic, dtype=np.bool), bp_init)

    return bps


def isbp_walk_for_bps(I, bpi):
    """
    Find branchpoints by walking from a pixel.

    Finds branchpoints by ensuring that all pixels in the sub-skeleton can be
    walked to from the set of already-found branchpoints, without visiting
    the same pixel more than once.

    Parameters
    ----------
    I : np.ndarray
        Binary image of a skeleton. In RivGraph, the skeleton is a reduced and
        padded version of Iskel.
    bpi : list
        Indices within I of the branchpoint to begin walk.

    Returns
    -------
    bpi : list
        Branchpoint indices in I.

    """
    bpi = set(bpi)

    # Use raveled image
    Ir = np.ravel(I)

    # Get edge pixels
    edgeidcs = iu.edge_coords(I.shape, dtype='flat')

    # Get emanators from first bp
    do_first = set()  # These are the 4-connected emanators
    emanators = set()
    for bp in bpi:
        emanators = emanators | set(iu.neighbors_flat(bp, Ir, I.shape[1])[0])
        do_first.update(iu.four_conn([bp], I)[0])

    # Create set containing pixels that have already been visited
    walked = bpi | emanators

    while emanators:

        if do_first:
            idx = do_first.pop()
            emanators.remove(idx)
        else:
            idx = emanators.pop()

        walking = 1
        while walking:

            walked.add(idx)
            neighs = set(iu.neighbors_flat(idx, Ir, I.shape[1])[0])
            neighs = neighs - walked

            if len(neighs) == 0:
                walking = 0

            elif len(neighs) == 1:
                idx = neighs.pop()
                if idx in edgeidcs:
                    walking = 0
            else:
                bpi.add(idx)
                fourconn = iu.four_conn([idx], I)[0]
                fourconn = [f for f in fourconn if f in neighs]
                do_first.update(fourconn)
                emanators = emanators | neighs
                walked.add(idx)
                walked.update(neighs)

    return bpi


def naxes_connectivity(I):
    """
    Compute number of axes of connectivity.

    Computes the number of axes of connectivity for each pixel in an input
    skeleton. The maximum is four; horizontal, vertical, and two diagonals.

    The number of axes of pixel connectivity is used to determine where to
    place branchpoints.

    Parameters
    ----------
    I : np.ndarray
        Binary image of a skeleton. In RivGraph, the skeleton is a reduced and
        padded version of Iskel.

    Returns
    -------
    Inax : np.ndarray
        Same shape as I; values correspond to the number of axes represented
        by each pixel's connectivity.

    """
    # Get the pixels we want to check (exclude edge pixels)
    Ir = np.ravel(I)
    edgeidcs = iu.edge_coords(I.shape, dtype='flat')

    allpix = set(np.where(Ir == 1)[0])

    dopix = allpix - edgeidcs
    savepix = list(dopix)

    naxes = []
    while dopix:
        pix = dopix.pop()
        count = 0
        if Ir[pix + 1] == 1 or Ir[pix - 1] == 1:
            count = count + 1
        if Ir[pix + I.shape[1]] == 1 or Ir[pix - I.shape[1]] == 1:
            count = count + 1
        if Ir[pix + 1 + I.shape[1]] == 1 or Ir[pix - 1 - I.shape[1]] == 1:
            count = count + 1
        if Ir[pix - 1 + I.shape[1]] == 1 or Ir[pix + 1 - I.shape[1]] == 1:
            count = count + 1
        naxes.append(count)

    Inax = np.zeros_like(Ir, dtype=np.uint8)
    Inax[savepix] = naxes
    Inax = np.reshape(Inax, I.shape)

    return Inax


""" Graveyard """

# def adjacent_bps(bp, Iskel, bps):

#     # Find branchpoint neighbors that are also branchpoints
#     bpneighs = walkable_neighbors([bp], Iskel)
#     bpneighs = [bpn for bpn in bpneighs if bpn not in bps]

#     bps_recheck = []
#     for bpcheck in bpneighs:
#         if is_bp(bpcheck, Iskel):
#             bps.append(bpcheck)

#     for bpcheck in bps_recheck:
#             bps = bps + adjacent_bps(bpcheck, Iskel, bps)

#     return bps


# def pattern_vals(basepattern):
#    """
#    Given an input pattern (3x3 or 2x2 numpy array), this function
#    (1) returns a convolution kernel of the same shape and
#    (2) the values of all rotations and mirrorings of the patterns convolved
#        with the kernel.
#    """
#
#    if basepattern[0].shape == (3,3):
#        kern = np.array([[256, 32, 4],[128, 16, 2], [64, 8, 1]], dtype=np.uint16)
#    elif basepattern[0].shape == (2,2):
#        kern = np.array([[8, 2], [4, 1]], dtype=np.uint16)
#    else:
#        raise RuntimeError('Input pattern is not 2x2 or 3x3.')
#
#    # Find the values of the convolution that match the pattern
#    convals = set()
#    for bp in basepattern:
#        for i in range(0,4):
#            convals.update([int(np.sum(kern[bp==1]))])
#            bp = np.rot90(bp, 1)
#        bp = np.flipud(bp)
#        for i in range(0,4):
#            convals.update([int(np.sum(kern[bp==1]))])
#            bp = np.rot90(bp, 1)
#        bp = np.fliplr(bp)
#        for i in range(0,4):
#            convals.update([int(np.sum(kern[bp==1]))])
#            bp = np.rot90(bp, 1)
#
#    return kern, convals

# def naxes_conn(idcs, I):
#    """
#    Counts the number of connected axes for a given flat index in I.
#    idcs must be a list, even if a single value.
#    """
#
#    Inax = np.ravel(naxes_connectivity(I))
#
#    naxesconn = []
#    for i in idcs:
#        naxesconn.append(int(Inax[i]))
#
#    return naxesconn
