#
#  reactions.py
#  EnumeratorProject
#
#  Created by Karthik Sarma on 4/18/2010.
#  Modifications by Casey Grun and Erik Winfree 8/15/2014.
#  Modifications by Stefan Badelt 09/2019

import copy

from peppercornenumerator.utils import Loop, wrap

from peppercornenumerator.objects import PepperComplex, PepperReaction, DSDDuplicationError
from peppercornenumerator.objects import make_pair_table, pair_table_to_dot_bracket

# Rate constant formulas
# ----------------------------------------------------------------------------

def opening_rate(length):
    """
    Rate constant formula for opening a duplex of a given `length`.
    """
    # use k_open = k_hybrid exp( (length * dG_bp + dG_assoc) / RT )
    # where k_hybrid = 3x10^6 /M/s   from Zhang&Winfree 2009 and Srinivas et al 2013
    #       dG_bp = -1.7 kcal/mol
    #       dG_assoc = +1.9 kcal/mol
    #       R = 0.001987 kcal/mol/K
    #       T = (273.15 + 25) K
    # return 7.41e7 * (0.0567 ** length)
    #
    # instead, use k_hybrid = L * 3 * 10^5, which matches the above for L=10.
    # this is to be consistent with the bimolecular binding rate.
    return length * 7.41e6 * (0.0567 ** length)


def polymer_link_length(before, after):
    """
    Effective length estimate for (ss+ds) linkers between two domains, 
    one or both of which may be open.
    """
    L_stem = 2.0 / 0.43  # rough equivalent number of single-stranded nucleotides to span a stem
    if not before.is_open:
        L_before = 1 + before.bases + before.stems + L_stem * before.stems
    if not after.is_open:
        L_after = 1 + after.bases + after.stems + L_stem * after.stems
    # for both closed & open cases, assume shorter length matters most
    if not after.is_open and not before.is_open:
        return min(L_before, L_after)
    if not before.is_open:
        return L_before
    if not after.is_open:
        return L_after
    assert False, "should not have reached this case -- how can both sides be open?"
    raw_input("bad bad bad -- computing polymer lengths in disconnected complex!")


def polymer_link_rate(linker_length):
    """
    Unimolecular hairpin closing rate, as a function of effective linker length. 
    """
    # a = 2.5e7    # per second; fit from data in Bonnet et al 1998 only
    a = 1e6        # per second; Kuznetsov et al 2008, Nayak et al 2012, Tsukanov et al 2013ab, all say at least 10x slower
    # fit from data in Bonnet et al 1998, consistent with Kuznetsov et al 2008
    b = -2.5
    # hairpin closing adapted (simplified) from data in Bonnet et al 1998, modified as above
    k = a * linker_length**b
    # hairpins shorter than about 4 nt can't close any faster.
    return min(k, 33000)


def binding_rate(length, before, after):
    """
    Rate constant formula for unimolecular binding of a domain of the given length.
    Could be zippering, hairpin closing, bubble closing, bulge formation, multiloop formation,
    depending on the flanking loops, which may be open or closed.
    """
    if not before.is_open and before.stems == 1 and before.bases == 0:
        if not after.is_open and after.stems == 1 and after.bases == 0:
            return 1e4  # bubble closing rate from Altan-Bonnet 2003
        # zippering from Wetmur&Davidson 1968, Gueron&Leroy 1995, Srinivas et al 2013, low end
        return (1e6) / length
    if not after.is_open and after.stems == 1 and after.bases == 0:
        # zippering from Wetmur&Davidson 1968, Gueron&Leroy 1995, Srinivas et al 2013, low end
        return (1e6) / length

    # bulge closing assumed to be similar to faster of two hairpin closings
    L = polymer_link_length(before, after)
    # hairpin closing adapted (simplified) from data in Bonnet et al 1998
    return polymer_link_rate(L)

# Diagram for 3-way branch migration, general case.
# Loops could be listed either 5'->3' or 3'->5, but they always go from
# invading domain to bound stem (non-inclusive).
#
#                before
#                _______  x (bound domain)
#               /       \____
# (invading) x |         ____
#               \_______/ x*
#
#                 after


def show_loops(before, after, message):
    """
    Debugging help: show (partial) loops returned by find_on_loop().  

    ! indicates a stem, | indicates open loop break.  
    """
    print "before: [ ",
    for step in before.parts:
        print " | " if step is None else step[0].name + ("!" if step[1] is not None else "") + " ",
    print " ] is_open = %r, stems = %d, bases = %d" % (before.is_open, before.stems, before.bases)
    print "after: [ ",
    for step in after.parts:
        print " | " if step is None else step[0].name + ("!" if step[1] is not None else "") + " ",
    print " ] is_open = %r, stems = %d, bases = %d" % (after.is_open, after.stems, after.bases)
    print(message)


def branch_3way_remote_rate(length, before, after, debug = False):
    """
    Rate constant formula for 3-way branch migration, possibly with a remote toehold.

    Args: 
        length (int): the length of the domain
        before (:obj:Loop): the loop object on the typical 3-way branch migration initiation site.
        after (:obj:Loop): the other (remote) loop object.
    """
    # step = 0.1e-3  # 100us branch migration step time from Srinivas et al 2013 (not relevant)
    # k_init = k_uni exp(-dGsp / RT) with k_uni = 7.5e7, dGsp = 7.3 kcal/mol,
    # T = 273.15 + 25 K, R = 0.001987 kcal/mol/K
    init = 3.0e-3  # sec, = 1/k_init from Srinivas et al 2013

    if debug :
        show_loops(before, after, "...before & after loops for 3-way branch migration...")

    # "standard" 3-way bm initiation (plus "after" being closed)
    if not before.is_open and before.stems == 1 and before.bases == 0:
        # each initiation has probability 1/length of succeeding.  
        # how long it takes doesn't matter.
        return 1.0 / init / length
    
    if debug:
        show_loops(before, after, 
                "run_tests.py should not have any remote toeholds for 3-way branch migration")

    # consider a slowdown analogous to Genot et al 2011 (remote) supp info derivation
    # bulge closing assumed to be similar to faster of two hairpin closings
    L = polymer_link_length(before, after)
    # how much slower than our (admittedly slow) zippering rate is this?
    ratio = polymer_link_rate(L) / (1e6)
    # we slow down initiation and thus success probability (note: ratio < 1/30)
    return ratio / init / length


def branch_4way_remote_rate(length, before, after, debug=False):
    """
    Rate constant formula for 4-way branch migration, possibly with a remote toehold
    """
    # rates recalculated from Nadine Dabby, PhD Thesis, 2013, based on
    # assuming last 6 bp dissociate faster than 4way bm step
    open_step = 107   # sec, = 1/k_first  (this is for open 4-way case only)
    # sec, = 1/k_bm     (this is used for initiating closed 4-way case;
    # consistent with Panyutin&Hsieh 1993)
    closed_step = 3.0

    # open_step = 200 # fudge !
    
    if debug:
        show_loops(before, after, "before & after loops for 4-way branch migration")

    if not before.is_open and not after.is_open:
        init = closed_step
        if before.bases == 0 and before.stems == 1 and after.bases == 0 and after.stems == 1:
            return 1.0 / init / length   # closed & ready-to-rock-and-roll 4 way initiation
    if before.is_open:
        init = open_step
        if after.bases == 0 and after.stems == 1:
            # we care about probability of taking this path, not actual time
            return 1.0 / init / length
    if after.is_open:
        init = open_step
        if before.bases == 0 and before.stems == 1:
            # we care about probability of taking this path, not actual time
            return 1.0 / init / length

    if debug: 
        show_loops(before, after, 
                "run_tests.py should not have any remote toeholds for 4-way branch migration")

    # consider a slowdown analogous to Genot et al 2011 (remote) supp info derivation
    # bulge closing assumed to be similar to faster of two hairpin closings
    L = polymer_link_length(before, after)
    # how much slower than our (admittedly slow) zippering rate is this?
    ratio = polymer_link_rate(L) / (1e6)
    # we slow down initiation and thus success probability (note: ratio < 1/30)
    return ratio / init / length


def bimolecular_binding_rate(length):
    """
    Rate constant formula for bimolecular association (binding).
    """
    # use k_hybrid = 3x10^6 /M/s   from Zhang&Winfree 2009
    # return 3.0e6
    #
    # instead, use k_hybrid = L * 3 * 10^5, which matches the above for L=10.
    # see Wetmur 1976 review, and Srinivas et al 2013 AEL model.
    # another motivation is to have binding rate approx = if a domain is
    # divided into two domains.
    return length * 3e5


# Reaction functions
# ----------------------------------------------------------------------------

def bind11(reactant, max_helix=True, remote=None):
    """
    Returns a list of reaction pathways which can be produced by 1-1 binding
    reactions of the argument complex. The 1-1 binding reaction is the
    hybridization of two complementary unpaired domains within a single complex
    to produce a single unpseudoknotted product complex.

    Note: Remote is ineffective, but may be set for convencience
    """
    
    reactions = []
    structure = reactant.pair_table

    # We iterate through all the domains
    for (strand_index, strand) in enumerate(structure):
        for (domain_index, domain) in enumerate(strand):

            # The displacing domain must be free
            if structure[strand_index][domain_index] is not None :
                continue

            start_loc = (strand_index, domain_index)

            # search both directions around the loop for a bound domain that
            # has the same sequence (and therefore can be displaced)
            results = find_on_loop(reactant, start_loc, filter_bind11)

            if results:
                assert len(results) == \
                        len(find_on_loop(reactant, start_loc, filter_bind11, direction=-1))

            for e, (invader, xlinker, target, ylinker) in enumerate(results):
                if max_helix:
                    invader, xlinker, target, ylinker = zipper(
                            reactant, invader[0], xlinker, target[0], ylinker, filter_bind11)
                results[e] = map(Loop, [invader, xlinker, target, ylinker])

            # build products
            for (loc1s, before, loc2s, after) in results:

                try :
                    (product,rotations) = do_bind11(reactant, loc1s.locs, loc2s.locs)
                except AssertionError:
                    continue

                try :
                    reaction = PepperReaction([reactant], [product], 'bind11')
                    reaction.meta = (loc1s, loc2s, before, after)
                    reaction.rotations = rotations
                except DSDDuplicationError, e :
                    reaction = e.existing

                # length of invading domain
                length = len(loc1s)

                # calculate reaction constant
                reaction.rate = binding_rate(length, before, after)

                reactions.append(reaction)

    # remove any duplicate reactions
    return sorted(list(set(reactions)))

def do_bind11(reactant, loc1s, loc2s, sanitycheck = False):
    """ Returns PepperComplex after the bind11 reaction. """
    struct = reactant.pair_table
    for loc1, loc2 in zip(loc1s, loc2s):
        assert struct[loc1[0]][loc1[1]] is None
        assert struct[loc2[0]][loc2[1]] is None
        struct[loc1[0]][loc1[1]] = loc2
        struct[loc2[0]][loc2[1]] = loc1
    newstr = pair_table_to_dot_bracket(struct)
    try:
        product = PepperComplex(reactant.sequence, newstr)
        product.pair_table = struct
        rotations = 0
    except DSDDuplicationError, e:
        product = e.existing
        rotations = e.rotations
    return (product, rotations)

def bind21(reactant1, reactant2, max_helix = True, remote=None):
    """
    Returns a list of reaction pathways which can be produced by 2-1 binding
    reactions of the argument complexes. The 2-1 binding reaction is the
    hybridization of two complementary unpaired domains, each in a different
    complex, to produce a single, unpseudoknotted product complex containing
    all of the strands contained in either of the original complexes.

    Note: remote is ineffective, but may be set for convencience
    """
    r1_doms = reactant1.available_domains
    r2_doms = reactant2.available_domains

    reactions = []

    # Iterate through all the free domains in reactant1
    for (dom1, strand_num1, dom_num1) in r1_doms:
        # For each, find any domains in reactant2 that could bind
        for (dom2, strand_num2, dom_num2) in r2_doms:
            # If it can pair, this is one possible reaction (this kind of
            # reaction cannot possibly produce a pseudoknotted structure)
            if (dom1.can_pair(dom2)):
                # combine the two complexes into one, but do not perform the association
                reactions.append(join_complexes_21(
                    reactant1, (strand_num1, dom_num1),
                    reactant2, (strand_num2, dom_num2)))
    
    output = []
    for complex, location1, location2 in reactions:
        # build "before" and "after" loop structures via find_on_loop ...
        out = find_on_loop(complex, location1, 
            lambda (dom1, struct1, loc1), (dom2, struct2, loc2) : 
                loc1 == location1 and loc2 == location2)

        [(loc1s, before, loc2s, after)] = out

        # zipper for max-helix semantics
        if max_helix :
            loc1s, before, loc2s, after = zipper(
                    complex, loc1s[0], before, loc2s[0], after, filter_bind11)

        [loc1s, before, loc2s, after] = map(Loop, [loc1s, before, loc2s, after])

        (product,rotations) = do_bind11(complex, loc1s.locs, loc2s.locs)

        try :
            reaction = PepperReaction(sorted([reactant1, reactant2]), [product], 'bind21')
        except DSDDuplicationError, e :
            #assert opening_rate(length) == PepperReaction.dictionary[e.solution].rate
            reaction = e.existing

        length = len(loc1s)
        reaction.rate = bimolecular_binding_rate(length)

        output.append(reaction)

    return sorted(list(set(output)))

def join_complexes_21(complex1, location1, complex2, location2):
    """
    Combines two complexes to form one complex, binding the domain in
    complex1 at location1 to the domain in complex2 at location2.

    Returns the new complex.
    """

    # make sure that this value is larger than any possible loc in the pair_table
    maxlen = complex1.size + complex2.size + 1

    if complex1.get_loop_index(location1) == 0 :
        seq1 = complex1.sequence
        ptb1 = complex1.pair_table
        loc1 = location1
        ptb1[loc1[0]][loc1[1]] = (maxlen,maxlen) # add an additional '(' 
    else :
        seen = False # don't break, otherwise you might lose the original strand ordering...
        for e, rot in enumerate(complex1.rotate(),1):
            tmp = complex1.rotate_location(location1, -e)
            if not seen and complex1.get_loop_index(tmp) == 0 :
                seq1 = complex1.sequence
                ptb1 = complex1.pair_table
                loc1 = tmp
                ptb1[loc1[0]][loc1[1]] = (maxlen,maxlen) # add an additional '(' 
                seen = True

    if complex2.get_loop_index(location2) == 0 :
        seq2 = complex2.sequence
        ptb2 = complex2.pair_table
        loc2 = location2
        ptb2[loc2[0]][loc2[1]] = (-1,-1) # add an additional ')' 
    else :
        seen = False # don't break, otherwise you might lose the original strand ordering...
        for e, rot in enumerate(complex2.rotate(),1):
            tmp = complex2.rotate_location(location2, -e)
            if not seen and complex2.get_loop_index(tmp) == 0 :
                seq2 = complex2.sequence
                ptb2 = complex2.pair_table
                loc2 = tmp
                ptb2[loc2[0]][loc2[1]] = (-1,-1) # add an additional ')' 
                seen = True

    # build the new sequence and structure *including* the new pair
    newseq = seq1 + ['+'] + seq2
    newstr = pair_table_to_dot_bracket(ptb1) + ['+'] + pair_table_to_dot_bracket(ptb2)

    # update loc2 from the new structure
    combined = make_pair_table(newstr)
    loc2 = combined[loc1[0]][loc1[1]]

    # remove the new pair again ...
    combined[loc1[0]][loc1[1]] = None
    combined[loc2[0]][loc2[1]] = None

    # update the structure to the unpaired (disconnected) version.
    newstr = pair_table_to_dot_bracket(combined)

    try :
        new_complex = PepperComplex(newseq, newstr)
    except DSDDuplicationError, e:
        new_complex = e.existing
        # strands may be re-ordered in new complex, so we need to back
        # out where the new strands ended up
        loc1 = new_complex.rotate_location(loc1, e.rotations)
        loc2 = new_complex.rotate_location(loc2, e.rotations)

    if loc1 > loc2:
        (loc1, loc2) = (loc2,loc1)

    return new_complex, loc1, loc2

def open(reactant, max_helix = True, release_11=6, release_1N=6):
    """
    Returns a list of reaction product sets that can be produced by the
    'open' reaction, in which a short helix dissociates. Each product
    set are the results of one particular dissociation; each strand in the
    reactant occurs exactly once in one of the complexes in the product set.

    A dissociation can happen to any helix under the threshold length

    """

    # remember the larger release cutoff; don't enumerate any reactions
    # for helices longer than this
    max_release = max(release_11, release_1N)

    reactions = []
    structure = reactant.pair_table

    def triple(loc):
        return (reactant.get_domain(loc), reactant.get_structure(loc), loc)

    # for no-max-helix mode:
    if not max_helix:
        # We iterate through all the domains
        for (strand_index, strand) in enumerate(structure):
            for (domain_index, domain) in enumerate(strand):

                # The bound domain must be... bound
                if reactant.get_structure((strand_index, domain_index)) is None :
                    continue

                bound_loc = (strand_index, domain_index)
                bound_domain = reactant.get_domain(bound_loc)

                (release_reactant, rotations) = do_single_open(reactant, bound_loc)
                product_set = release_reactant.split()
                meta = (Loop([triple(bound_loc)]),
                        Loop([triple(reactant.get_structure(bound_loc))]), None, None)
                reactions.append((product_set, rotations, len(bound_domain),
                    meta))

    # for max-helix mode:
    else:
        # We loop through all stands, domains
        for (strand_index, strand) in enumerate(structure):
            for (domain_index, domain) in enumerate(strand):
                # If the domain is unpaired, skip it
                if (structure[strand_index][domain_index] is None):
                    continue

                # A: Strand/domain position on "top" strand - CG 5/21
                helix_startA = [strand_index, domain_index]

                # B: Strand/domain position on "bottom" strand - CG 5/21
                helix_startB = list(structure[strand_index][domain_index])

                # If the domain is bound to an earlier domain, then we have
                # already considered it, so skip it
                if (helix_startB < helix_startA):
                    continue

                helix_endA = helix_startA[:]
                helix_endB = helix_startB[:]

                bound_loc = (strand_index, domain_index)
                bound_domain = reactant.get_domain(bound_loc)
                helix_length = len(bound_domain)

                # Now iterate through the whole helix to find the other end of
                # this one (The helix ends at the first strand break from
                # either direction)
                while True:
                    # Strands run in opposite directions, so A must be incremented
                    # and B decremented in order that both pointers move "right"
                    # along the helix- CG 5/21
                    helix_endA[1] += 1
                    helix_endB[1] -= 1

                    # If one of the strands has broken, the helix has ended
                    if helix_endA[1] >= reactant.strand_length(helix_endA[0]) :
                        break
                    elif helix_endB[1] < 0 :
                        break

                    # If these domains aren't bound to each other, the helix has ended
                    if (tuple(helix_endA) != structure[helix_endB[0]][helix_endB[1]]):
                        break

                    # Add the current domain to the current helix
                    temp_bl = (helix_endA[0], helix_endA[1])
                    helix_length += len(reactant.get_domain(temp_bl))

                # We must also iterate in the other direction
                while True:
                    helix_startA[1] -= 1
                    helix_startB[1] += 1

                    # If one of the strands has broken, the helix has ended
                    if helix_startA[1] < 0 :
                        break
                    elif helix_startB[1] >= reactant.strand_length(helix_startB[0]):
                        break

                    # If these domains aren't bound to each other, the helix has ended
                    if tuple(helix_startA) != structure[helix_startB[0]][helix_startB[1]] :
                        break

                    # Add the current domain to the current helix
                    temp_bl = (helix_startA[0], helix_startA[1])
                    helix_length += len(reactant.get_domain(temp_bl))

                # Move start location to the first domain in the helix
                helix_startA[1] += 1
                helix_startB[1] -= 1

                # If the helix is short enough, we have a reaction
                if (helix_length <= max_release):

                    new_struct = reactant.pair_table

                    # Delete all the pairs in the released helix
                    for dom in range(helix_startA[1], helix_endA[1]):
                        bound_loc = reactant.get_structure((helix_startA[0], dom))
                        new_struct[helix_startA[0]][dom] = None
                        new_struct[bound_loc[0]][bound_loc[1]] = None

                    newstr = pair_table_to_dot_bracket(new_struct)

                    try:
                        release_reactant = PepperComplex(reactant.sequence, newstr)
                        rotations = 0
                    except DSDDuplicationError, e:
                        release_reactant = e.existing
                        rotations = e.rotations

                    product_set = release_reactant.split()
                    meta = None
                    reactions.append((product_set, rotations, helix_length, meta))

    output = []
    for product_set, rotations, length, meta in reactions:
        try :
            reaction = PepperReaction([reactant], sorted(product_set), 'open')
            reaction.rotations = rotations
            reaction.meta = meta
        except DSDDuplicationError, e :
            reaction = e.existing

        # discard reactions where the release cutoff is greater than the threshold
        if len(reaction.products) == 1 and length > release_11:
            continue
        elif len(reaction.products) > 1 and length > release_1N:
            continue

        reaction.rate = opening_rate(length)
        output.append(reaction)

    return sorted(list(set(output)))

def do_single_open(reactant, loc):
    struct = reactant.pair_table
    loc1 = loc
    loc2 = struct[loc1[0]][loc1[1]]
    assert struct[loc2[0]][loc2[1]] == loc1
    struct[loc1[0]][loc1[1]] = None
    struct[loc2[0]][loc2[1]] = None
    newstr = pair_table_to_dot_bracket(struct)
    try:
        product = PepperComplex(reactant.sequence, newstr)
        product.pair_table = struct
        rotations = 0
    except DSDDuplicationError, e:
        product = e.existing
        rotations = e.rotations
    return (product, rotations)

def branch_3way(reactant, max_helix = True, remote=True):
    """
    Returns a list of reaction pathways that can be created through one
    iteration of a 3 way branch migration reaction (more than one molecule may
    be produced by a reaction because branch migration can liberate strands and
    complexes).
    """

    reactions = []

    reactions = []
    structure = reactant.pair_table

    # We iterate through all the domains
    for (strand_index, strand) in enumerate(structure):
        for (domain_index, domain) in enumerate(strand):

            # The displacing domain must be free
            if (structure[strand_index][domain_index] is not None):
                continue

            # search 5'->3' and 3'->5' directions around the loop for a bound
            # domain that is complementary (and therefore can be displaced)

            start_loc = (strand_index, domain_index)

            # build products
            fwresults = find_on_loop(reactant, start_loc, filter_3way, direction=1)
            bwresults = find_on_loop(reactant, start_loc, filter_3way, direction=-1)

            results = []
            for (invader, xlinker, target, ylinker) in fwresults:
                if max_helix:
                    invader, xlinker, target, ylinker = zipper(
                            reactant, invader[0], xlinker, target[0], ylinker, filter_3way)
                ylinker += invader
                results.append(map(Loop, [invader[::-1], xlinker, target[::-1], ylinker]))

            for (invader, xlinker, target, ylinker) in bwresults:
                if max_helix:
                    invader, xlinker, target, ylinker = zipper(
                            reactant, invader[0], xlinker, target[0], ylinker, filter_3way)
                ylinker += invader[::-1]
                results.append(map(Loop, [invader, xlinker, target, ylinker]))

            for (displacing, before, bound, after) in results:
                (products, rotations) = do_3way_migration(reactant,
                        list(displacing.locs), list(bound.locs))

                try :
                    reaction = PepperReaction([reactant], products, 'branch-3way')
                    reaction.meta = (displacing, bound, before, after)
                    reaction.rotations = rotations
                except DSDDuplicationError, e :
                    reaction = e.existing

                # skip remote toehold reactions if directed
                if not remote :
                    if not (not before.is_open and before.stems == 1 and before.bases == 0):
                        # print "Rejecting... " + reaction.kernel_string
                        # import pdb; pdb.set_trace()
                        continue

                # calculate reaction constant
                reaction.rate = branch_3way_remote_rate(len(displacing), before, after)

                reactions.append(reaction)

    # Remove any duplicate reactions
    return sorted(list(set(reactions)))

def do_3way_migration(reactant, displacing_locs, bound_locs):
    """
    Each location in displacing_locs will end up bound to the corresponding
    location in bound_locs. The stuff bound to bound_locs will end up un-bound
    """

    def update_structure(struct, displacing_loc, new_bound_loc):
        """
        displacing_loc will be bound to new_bound_loc; whatever new_bound_loc
        was bound to will be unbound.
        """
        displaced_loc = struct[new_bound_loc[0]][new_bound_loc[1]]

        assert struct[displacing_loc[0]][displacing_loc[1]] is None
        assert struct[new_bound_loc[0]][new_bound_loc[1]] is not None
        assert struct[displaced_loc[0]][displaced_loc[1]] is not None
        assert struct[displaced_loc[0]][displaced_loc[1]] == new_bound_loc
    
        struct[displacing_loc[0]][displacing_loc[1]] = new_bound_loc
        struct[new_bound_loc[0]][new_bound_loc[1]] = displacing_loc
        struct[displaced_loc[0]][displaced_loc[1]] = None

    struct = reactant.pair_table

    for displacing_loc, new_bound_loc in zip(displacing_locs, bound_locs):
        update_structure(struct, displacing_loc, new_bound_loc)

    newstr = pair_table_to_dot_bracket(struct)

    try:
        product = PepperComplex(reactant.sequence, newstr)
        product.pair_table = struct
        rotations = 0
    except DSDDuplicationError, e:
        product = e.existing
        rotations = e.rotations
  
    return (product.split(), rotations)

def branch_4way(reactant, max_helix = False, remote=True):
    """
    Returns a list of complex sets that can be created through one iteration of
    a 4 way branch migration reaction (each set consists of the molecules that
    result from the iteration; more than one molecule may result because branch
    migration can liberate strands and complexes).
    """

    reactions = []
    structure = reactant.pair_table

    # We loop through all domains
    for (strand_index, strand) in enumerate(structure):
        for (domain_index, domain) in enumerate(strand):

            # Unbound domains can't participate in branch migration
            if (structure[strand_index][domain_index] is None):
                continue

            start_loc = (strand_index, domain_index)

            # searches only 5'->3' direction around the loop for a bound domain that
            # has the same sequence (and therefore can be displaced)
            #
            #   z  _~_  z* (displacing)
            #  ___/   \___>
            #
            # <___     ___
            #     \_ _/
            #   z*  ~   z
            #

            # build products
            results = find_on_loop(reactant, start_loc, filter_4way)

            for e, (invader, xlinker, target, ylinker) in enumerate(results):
                if max_helix:
                    invader, _, target, _ = zipper(
                            reactant, invader[0], None, target[0], None, filter_4way)
                results[e] = map(Loop, [invader, xlinker, target, ylinker])

            for (displacing, before, displaced, after) in results:
                (products,rotations) = do_4way_migration(reactant, displacing.locs,
                            (structure[dl[0]][dl[1]] for dl in displacing.locs),
                            (structure[bl[0]][bl[1]] for bl in displaced.locs), 
                            displaced.locs)

                try :
                    reaction = PepperReaction([reactant], products, 'branch-4way')
                    reaction.meta = (displacing, displaced, before, after)
                    reaction.rotations = rotations
                except DSDDuplicationError, e :
                    reaction = e.existing

                # skip remote toehold reactions
                if not remote:
                    # NOTE: both sides need to be remote!
                    if not ((not after.is_open and after.stems == 1 and after.bases == 0) or
                            (not before.is_open and before.stems == 1 and before.bases == 0)):
                        continue

                # calculate reaction constant
                reaction.rate = branch_4way_remote_rate(len(displacing), before, after)

                reactions.append(reaction)

    # remove any duplicate reactions
    return sorted(list(set(reactions)))

def do_4way_migration(reactant, loc1s, loc2s, loc3s, loc4s):
    """
    Perform a sequence of max_helix 4-way branch migration reactions.
    """
    def update_structure(struct, loc1, loc2, loc3, loc4):
        """
        Performs a 4 way branch migration on a copy of reactant, with loc1 as the
        displacing domain, loc2 as the domain displaced from loc1, loc3 as the
        template domain, and loc4 as the domain displaced from loc3. Returns the
        set of complexes produced by this reaction (may be one or more complexes).
    
        loc1:loc2, loc3:loc4 -> loc1:loc3, loc2:loc4
        """
        assert None not in (loc1, loc2, loc3, loc4)
        assert struct[loc1[0]][loc1[1]] == loc2
        assert struct[loc3[0]][loc3[1]] == loc4
        assert struct[loc2[0]][loc2[1]] == loc1
        assert struct[loc4[0]][loc4[1]] == loc3

        struct[loc1[0]][loc1[1]] = loc3
        struct[loc3[0]][loc3[1]] = loc1
        struct[loc2[0]][loc2[1]] = loc4
        struct[loc4[0]][loc4[1]] = loc2

    struct = reactant.pair_table
    for loc1, loc2, loc3, loc4 in zip(loc1s, loc2s, loc3s, loc4s):
        update_structure(struct, loc1, loc2, loc3, loc4)
    newstr = pair_table_to_dot_bracket(struct)
    try:
        product = PepperComplex(reactant.sequence, newstr)
        product.pair_table = struct
        rotations = 0
    except DSDDuplicationError, e:
        product = e.existing
        rotations = e.rotations
    return (product.split(), rotations)

# Filter functions for find_on_loop()
def filter_bind11((dom1, struct1, loc1), (dom2, struct2, loc2)):
    return struct1 is None and struct2 is None and dom2.can_pair(dom1)

def filter_3way((dom1, struct1, loc1), (dom2, struct2, loc2)):
    return (struct1 is None) and (struct2 is not None) and dom1.can_pair(dom2)

def filter_4way((dom1, struct1, loc1), (dom2, struct2, loc2)):
    return struct1 is not None and struct2 is not None and dom1 == dom2

def find_on_loop(reactant, start_loc, pattern, direction=1):
    """Find a reaction pattern within a loop.
    
    Starts at a particular locus and searches for every possible pattern that
    preseves secondary structure (matches within the "loop").  Where a loop
    involves stems, only one of the complementary domains will be listed in the
    array of tuples, specifically, the "first" one in the search direction.
    Thus, a multiloop with n unpaired domains and m stems will result, for
    closed loops, in `len(before+after) == n+m-2`, as the match location and
    `start_loc` are omitted.

    Note 1: `before` and `after` refer to the partial loops between `start_loc`
    and each of the results, _in the `direction`_ of the search. For example:

       A
          ____
         /    \ 
     x  |     |  x*
        |
         \____> 3'

            B

    If `start_loc` pointed to `x` and `direction` is +1, then `before` would
    be `A` and `after` would be `B`. If instead `direction` is -1, then
    `before` is `B` and `after` is `A`.  
    Note 2: If the domain passed to `start_loc` is a duplex, the results may
    be unexpected:

           ___  x  ___
    5' ___/   \___/   \___
    3' ___  A  ___  B  ___)
          \___/   \___/
                x*

    Notice that the duplex x() participates in two internal loops (A and B).
    By convention, the internal loop considered is the _internal loop which
    encloses this domain_. That means if you pass domain x and +1, you'll get
    loop A, whereas if you pass x and -1, you'll get loop B. This is in an
    attempt to be consistent with the case where you pass an unpaired domain
    (and therefore the internal loop searched is the one which encloses the
    unpaired domain).
  
    Args:
        reactant (:obj:) = The reactant complex object.
        start_loc ((int,int)) = A tuple pointing to the respective strand and
            domain indices for reactant.pair_table
        pattern (function) = A pointer to a pattern match function which
            determines if there exists a valid binding partner for the start locus.
            The function takes two arguments containing (domain, paired, locus)
            and returns True or False.
        directions (optional: -1,+1): Searching for binding partners in 
            5'->3' (+1) or 3'->5' (-1) direction.

    Returns:
        TODO

    """

    results = []
    loop = []
    def triple(loc):
        return (reactant.get_domain(loc), reactant.get_structure(loc), loc)

    # We now follow the external loop from the starting pair
    # searching for a bound domain to displace
    bound_loc = start_loc

    # Avoid getting stuck inside an internal loop enclosed by this domain,
    # if the starting domain is a duplex.
    #
    #   1      2
    #  ___________
    #  ____  _____
    #   1*  /  2*
    #
    #  If we start at domain 1, going in the - direction, then
    #  immediately continue to the next domain, we'll go to 1*
    if reactant.get_structure(bound_loc) is not None:
        bound_loc = reactant.get_structure(bound_loc)
    
    # Follow the external loop to the end
    while True:
        # move to the next domain in the indicated direction
        # (+1 = 5' -> 3', -1 = 3' -> 5')
        bound_loc = (bound_loc[0], bound_loc[1] + direction)

        # if we've reached the end of the strand (5')
        if (bound_loc[1] == -1):
            # Continue to next strand
            bound_loc = (wrap(bound_loc[0] - 1, reactant.size),)
            bound_loc = (bound_loc[0], reactant.strand_length(bound_loc[0]))
            loop.append(None)
            continue

        # if we've reached the end of the strand (3')
        if (bound_loc[1] == reactant.strand_length(bound_loc[0])):
            # Continue to next strand
            bound_loc = (wrap(bound_loc[0] + 1, reactant.size), -1)
            loop.append(None)
            continue

        if bound_loc == start_loc:
            # We've returned to the original location of the displacing domain
            break

        # try to match the pattern function
        if pattern(triple(start_loc), triple(bound_loc)):
            # append the location
            results.append((bound_loc, len(loop)))

        # store unpaired domains and "first" domain of each stem
        loop.append(triple(bound_loc))
 
        # if the domain at bound_loc is unbound
        if reactant.get_structure(bound_loc) is None:
            # look to the next domain
            continue
        else :
            # follow the structure to stay on the same loop
            bound_loc = reactant.get_structure(bound_loc)

    return [([triple(start_loc)],   # invading domain
             loop[:i],              # first linker 
             [triple(bound_loc)],   # target domain
             loop[i+1:]) for (bound_loc, i) in results]

def zipper(reactant, start_trp, before, bound_trp, after, pattern):
    """Max-helix mode zipping to extend a given move type.

    Takes a result from `find_on_loop` and finds as many adjacent domains as
    possible such that the `pattern` function still returns True.

    For example, if `start_loc` was b1 and `bound_loc` was b1*, and the pattern
    function specified that the domain at `start_loc` must be complementary to
    the domain at `bound_loc`, then the function would return [b1,b2] as
    start_locs and [b1*, b2*] as bound_locs

            b1* b2*
            ______
         __/      \__>
        <__        __
           \______/
            b1  b2

    Note that 4-way branch migration max-helix never extends into (changes) the 
    before / after loops, so it is safe to pass None instead.

    Returns:
        start_locs (extended list of triples)
        before (reduced list of triples)
        bound_locs (extended list of triples)
        after (reduced list of triples)
    """

    def triple(loc):
        return (reactant.get_domain(loc), reactant.get_structure(loc), loc)

    assert pattern(start_trp,bound_trp)

    def extend_match(start_loc, bound_loc, sdir, bdir):
        """
        Move upstream or downstream from start locus and bound locus and check
        if pattern condition still applies.

        Accesses reactant, start_loc, bound_loc, pattern, 
        
        """
        (sstrand, sdomain) = start_loc
        (bstrand, bdomain) = bound_loc

        start_pair = reactant.get_structure(start_loc)
        bound_pair = reactant.get_structure(bound_loc)

        sloc = (sstrand, sdomain + sdir)
        bloc = (bstrand, bdomain + bdir)

        try:
            spair = reactant.get_structure(sloc)
            bpair = reactant.get_structure(bloc)
        except IndexError:
            # sdomain is no longer on sstrand or 
            # bdomain is no longer on bstrand
            return

        if (start_pair is None) != (spair is None): return
        if (bound_pair is None) != (bpair is None): return

            # ddomain hasn't passed bound_loc
        if ((cmp(sloc, bound_loc) == cmp(start_loc, bound_loc)) and
            # and bdomain hasn't passed start_loc
            (cmp(bloc, start_loc) == cmp(bound_loc, start_loc)) and

            # if paired, then also the paired domain must be adjacent
            ((start_pair is None) and (spair is None) or
                start_pair[0] == spair[0] and         # same strand!
                start_pair[1] == spair[1] + sdir) and # adjacent!

            # if paired, then also the paired domain must be adjacent
            ((bound_pair is None) and (bpair is None) or
                bound_pair[0] == bpair[0] and         # same strand!
                bound_pair[1] == bpair[1] + bdir) and # adjacent!

            # and pattern condition still applies
            pattern(triple(sloc), triple(bloc))):

            # add new positions to list
            if sdir == 1:
                start_locs.append(triple(sloc))
                if before and before[0] == triple(sloc):
                    before.pop(0)
            else :
                start_locs[:0] = [triple(sloc)]
                if after and after[-1] == triple(sloc):
                    after.pop(-1)

            if bdir == 1:
                bound_locs[:0] = [triple(bloc)]
                if after and after[0] == triple(bloc):
                    after.pop(0)
            else :
                bound_locs.append(triple(bloc))
                if before and before[-1] == triple(bloc):
                    before.pop(-1)

            extend_match(sloc, bloc, sdir, bdir)

        return

    start_locs = [start_trp]
    bound_locs = [bound_trp]

    if filter_4way(start_trp,bound_trp):
        extend_match(start_trp[2], bound_trp[2], sdir = 1, bdir = 1)
        bound_locs = bound_locs[::-1]
    else :
        extend_match(start_trp[2], bound_trp[2], sdir = 1, bdir = -1)
        extend_match(start_trp[2], bound_trp[2], sdir = -1, bdir = 1)

    return start_locs, before, bound_locs, after

