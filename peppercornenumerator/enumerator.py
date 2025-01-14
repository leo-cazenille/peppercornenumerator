#
#  enumerator.py
#  EnumeratorProject
#
#  Created by Karthik Sarma on 4/18/10.
#  Modified by Stefan Badelt
#

import sys
import math
import logging

from peppercornenumerator.objects import PepperMacrostate, PepperComplex
from peppercornenumerator.objects import DSDDuplicationError, DSDObjectsError
import peppercornenumerator.utils as utils
import peppercornenumerator.reactions as reactlib


# There should be better control of this limit -- only set it when
# necessary (Erik Winfree based on Chris Thachuk's advice...)
sys.setrecursionlimit(20000)


FAST_REACTIONS = {1: [reactlib.bind11, reactlib.open,
                      reactlib.branch_3way, reactlib.branch_4way]}
"""
Dictionary of reaction functions considered *fast* for a given "arity".
Keys are arities (e.g. 1 = unimolecular, 2 = bimolecular, 3 = trimolecular,
etc.), and values are lists of reaction functions. Currently, only
unimolecular fast reactions (arity = 1) are supported.
"""

SLOW_REACTIONS = {
    1: [],
    2: [reactlib.bind21]
}
"""
A dictionary of reaction functions considered *slow* for a given "arity".
Keys are arities (e.g. 1 = unimolecular, 2 = bimolecular, 3 = trimolecular,
etc.), and values are lists of reaction functions. Currently, only
bimolecular reactions (arity = 2) are by default slow. However, when using
k-fast, also unimolecular reactions can fall into the *slow* regime.
"""

class PolymerizationError(Exception):
    """Error class to catch polymerization."""

    def __init__(self, msg, val=None):
        self.message = msg
        if val :
            self.message += " ({})".format(val)
        super(PolymerizationError, self).__init__(self.message) 


class Enumerator(object):
    """
    Represents a single enumerator instance, consisting of all the information
    required for a reaction graph. This class is the coordinator for the state
    enumerator. Enumerators have immutable starting conditions. 
    """

    def __init__(self, initial_complexes, initial_reactions=None):
        """
        Initializes the enumerator with a list of initial complexes.

        Note: The optional arguments 'strands' and 'domains' are there for
        backwards-compatibility and will be remove at some point. Ignoring them
        below breaks unit-tests - why? (1) sometimes complementary domains are
        specified that are actually not present in any of the complexes, (2)
        conflicts with strand names in the original kernel format (where
        explicit strand specifications are supported).
        """
        # System initialization
        self._initial_complexes = initial_complexes
        for cplx in initial_complexes:
            if not cplx.is_connected:
                raise utils.PeppercornUsageError('Initial complex is not connected: {}'.format(cplx))
        self._domains = self.get_domains(self._initial_complexes)

        # list containing all detailed reactions after enumeration
        if initial_reactions:
            self._reactions = initial_reactions
        else :
            self._reactions = []

        self._complexes = None
        self._resting_complexes = None
        self._transient_complexes = None
        self._resting_macrostates = None

        self.DFS = True
        self.interruptible = True
        self.interactive = False
        
        # Polymerization settings to prevent infinite looping
        self.max_complex_size = 6
        self.max_complex_count = 200
        self.max_reaction_count = 1000

        #
        # Set separation of timescales for *unimolecular* reactions.
        #
        #  ignore-reaction | resting-set | transient-state
        # -----------------|---------------|---------------> rate
        #                k_slow          k_fast
        #
        # Default: All unimolecular reactions are transient, none are ignored.
        #
        self._k_slow = 0 
        self._k_fast = 0
        self._p_min = 0
        self._p_loc = 0

        # Settings for reaction enumeration. 
        self._max_helix = True
        self._remote = True
        self._release_11 = 6
        self._release_1N = 6

    @property
    def max_complex_size(self):
        return self._max_complex_size

    @max_complex_size.setter
    def max_complex_size(self, value):
        self._max_complex_size = value

    @property
    def max_reaction_count(self):
        return self._max_reaction_count

    @max_reaction_count.setter
    def max_reaction_count(self, value):
        self._max_reaction_count = value

    @property
    def max_complex_count(self):
        return self._max_complex_count

    @max_complex_count.setter
    def max_complex_count(self, value):
        self._max_complex_count = value

    @property
    def k_slow(self):
        return self._k_slow

    @k_slow.setter
    def k_slow(self, value):
        self._k_slow = value

    @property
    def k_fast(self):
        return self._k_fast

    @k_fast.setter
    def k_fast(self, value):
        self._k_fast = value

    @property
    def release_cutoff(self):
        if self._release_11 != self._release_1N :
            raise utils.PeppercornUsageError('Ambiguous release cutoff request.')
        return self._release_11

    @release_cutoff.setter
    def release_cutoff(self, value):
        assert isinstance(value, int)
        self._release_11 = value
        self._release_1N = value

    @property
    def release_cutoff_1_1(self):
        return self._release_11

    @release_cutoff_1_1.setter
    def release_cutoff_1_1(self, value):
        assert isinstance(value, int)
        self._release_11 = value

    @property
    def release_cutoff_1_N(self):
        return self._release_1N

    @release_cutoff_1_N.setter
    def release_cutoff_1_N(self, value):
        assert isinstance(value, int)
        self._release_1N = value

    @property
    def remote_migration(self):
        return self._remote

    @remote_migration.setter
    def remote_migration(self, remote):
        assert isinstance(remote, bool)
        self._remote = remote

    @property
    def max_helix_migration(self):
        """ """
        return self._max_helix

    @max_helix_migration.setter
    def max_helix_migration(self, max_helix):
      self._max_helix = max_helix

    # ------------
    @property
    def initial_complexes(self):
        """
        Complexes present in the system's initial configuration
        """
        return self._initial_complexes[:]

    @property
    def domains(self):
        return self._domains[:]

    @property
    def reactions(self):
        """
        List of reactions enumerated. :py:meth:`.enumerate` must be
        called before access.
        """
        return list(set(self._reactions))

    @property
    def resting_sets(self):
        """
        List of resting states enumerated. :py:meth:`.enumerate` must be
        called before access.
        """
        if self._resting_macrostates is None:
            raise utils.PeppercornUsageError("enumerate not yet called!")
        return self._resting_macrostates[:]

    @property
    def complexes(self):
        """
        List of complexes enumerated. :py:meth:`.enumerate` must be
        called before access.
        """
        if self._complexes is None:
            raise utils.PeppercornUsageError("enumerate not yet called!")
        return self._complexes[:]

    @property
    def resting_complexes(self):
        """
        List of complexes enumerated that are within resting states.
        :py:meth:`.enumerate` must be called before access.
        """
        if self._resting_complexes is None:
            raise utils.PeppercornUsageError("enumerate not yet called!")
        return self._resting_complexes[:]

    @property
    def transient_complexes(self):
        """
        List of complexes enumerated that are not within resting sets (e.g.
        complexes which are transient). :py:meth:`.enumerate` must be
        called before access.
        """
        if self._transient_complexes is None:
            raise utils.PeppercornUsageError("enumerate not yet called!")
        return self._transient_complexes[:]

    def __eq__(self, object):
        return (sorted(self.domains) == sorted(object.domains)) and \
            (sorted(self.initial_complexes) == sorted(object.initial_complexes)) and \
            (sorted(self.reactions) == sorted(object.reactions)) and \
            (sorted(self.resting_sets) == sorted(object.resting_sets)) and \
            (sorted(self.complexes) == sorted(object.complexes)) and \
            (sorted(self.resting_complexes) == sorted(object.resting_complexes)) and \
            (sorted(self.transient_complexes) == sorted(object.transient_complexes))

    def get_domains(self, initial_complexes):
        domains = set()
        for cplx in initial_complexes:
            map(lambda d: domains.add(d), cplx.domains)
        return list(domains)

    def dry_run(self):
        """
        Make it look like you've enumerated, but actually do nothing.
        """
        self._complexes = self.initial_complexes[:]

        # This is not nice, the input might not be a resting complex
        self._resting_complexes = self._complexes[:]

        self._resting_macrostates = []

        self._transient_complexes = []

    def enumerate(self):
        """
        Generates the reaction graph consisting of all complexes reachable from
        the initial set of complexes. Produces a full list of :py:meth:`complexes`, resting
        sets, and :py:meth:`reactions, which are stored in the associated members of this
        class.
        """

        # Will be called once enumeration halts, either because it's finished or
        # because too many complexes/reactions have been enumerated
        def finish(premature=False):
            # copy E and T into complexes
            self._complexes += (self._E)
            self._complexes += (self._T)

            # preserve resting and transient complexes separately
            self._transient_complexes = self._T
            self._resting_complexes = self._E

            # If we're bailing because of too many reactions or complexes, search
            # self._reactions to ensure there are no reactions which contain
            # products that never made it into self._complexes...
            if premature:
                self._resting_complexes += self._S
                self._complexes += self._S
                complexes = set(self._complexes)

                rm_reactions = []
                for reaction in self.reactions:
                    #NOTE: This should only matter in the Ctrl-C case, right?
                    reaction_ok = all((prod in complexes) for prod in reaction.products) and \
                                  all((reac in complexes) for reac in reaction.reactants)

                    if reaction_ok:
                        pass
                    else :
                        rm_reactions.append(reaction)

                self._reactions = [x for x in self._reactions if x not in rm_reactions]

        # List E contains enumerated resting complexes. Every time a new
        # complex is added (from S), all cross reactions with other resting
        # complexes are enumerated. Complexes remain in this list throughout
        # function execution, the products of slow reactions go into list B.
        self._E = []

        # List S contains newly determined resting complexes after all fast
        # reactions have been enumerated. They will be moved to E and thereby
        # tested for cross reactions with set E. 
        self._S = []

        # List T contains newly determined transient states after fast-reaction
        # enumeration. These complexes will remain in this list throughout
        # function execution.
        self._T = []

        # List N contains the neighborhood of some initial complexes with all
        # fast reactions enumerated. Complexes in N have not yet been
        # characterized as transient or resting sets.
        self._N = []

        # List F contains components of the current 'neighborhood' which have
        # not yet been reactants for potential fast reactions.  They will be
        # moved to N once they were enumerated.
        self._F = []

        # List B contains initial complexes, or products of bimolecular
        # reactions that have had no reactions enumerated yet. They will be
        # moved to F for their fast neighborhood to be enumerated.
        self._B = self.initial_complexes[:]

        self._complexes = []
        self._resting_macrostates = []

        def do_enumerate():
            logging.debug("Fast reactions from initial complexes...")
            while len(self._B) > 0:
                # Generate a neighborhood from `source`
                source = self._B.pop()
                self.process_neighborhood(source)

            # Consider slow reactions between resting set complexes
            logging.debug("Slow reactions between resting set complexes...")
            while len(self._S) > 0:

                # Find slow reactions from `element`
                if self.DFS:
                    element = self._S.pop()
                else:
                    element = self._S.pop(0)

                logging.debug("Slow reactions from complex {:s} ({:d} remaining in S)".format(
                    element, len(self._S)))
                slow_reactions = self.get_slow_reactions(element)
                self._E.append(element)

                # Find the new complexes which were generated
                self._B = self.get_new_products(slow_reactions)
                self._reactions += (slow_reactions)
                logging.debug("Generated {:d} new slow reactions".format(len(slow_reactions)))
                logging.debug("Generated {:d} new products".format(len(self._B)))

                # Display new reactions in interactive mode
                if self.interactive:
                    self.reactions_interactive(element, slow_reactions, 'slow')

                # Now find all complexes reachable by fast reactions from these new complexes
                while len(self._B) > 0:

                    # Check whether too many complexes have been generated
                    if (len(self._E) + len(self._T) + len(self._S) > self._max_complex_count):
                        raise PolymerizationError("Too many complexes enumerated!", 
                                len(self._E) + len(self._T) + len(self._S))

                    # Check whether too many reactions have been generated
                    if (len(self._reactions) > self._max_reaction_count):
                        raise PolymerizationError("Too many reactions enumerated!", 
                                len(self._reactions))

                    # Generate a neighborhood from `source`
                    source = self._B.pop()
                    self.process_neighborhood(source)

        if self.interruptible:
            try:
                do_enumerate()
                finish()
            except KeyboardInterrupt:
                logging.warning("Interrupted; gracefully exiting...")
                finish(premature=True)
            except PolymerizationError as e:
                logging.exception(e)
                # print e
                # import traceback
                # print traceback.format_exc()
                logging.error("Polymerization error; gracefully exiting...")
                finish(premature=True)
        else:
            do_enumerate()
            finish()

    def reactions_interactive(self, root, reactions, rtype='fast'):
        """
        Prints the passed reactions as a kernel string, then waits for keyboard
        input before continuing.
        """
        print "{} = {} ({})".format(root.name, root.kernel_string, rtype)
        print
        for r in reactions:
            print r.kernel_string
        if len(reactions) is 0:
            print "(No {} reactions)".format(rtype)
        print 
        utils.wait_for_input()

    def process_neighborhood(self, source):
        """ Enumerate neighborhood of fast reactions.

        Takes a single complex, generates the 'neighborhood' of complexes
        reachable from that complex through fast reactions, classifies these
        complexes as transient or resting complexes, and modifies the global
        lists and list of reactions accordingly.

        Args:
            source (:obj:`utils.Complex`): Initial complex to generate a
                neighborhood of fast reactions.
        """

        assert len(self._F) == 0
        self._F = [source]

        # N_reactions holds reactions which are part of the current neighborhood
        N_reactions = []

        logging.debug("Processing neighborhood: %s" % source)

        try:
            # First find all of the complexes accessible through horizontal or
            # downhill reactions starting with the source
            while len(self._F) > 0 :

                # Find fast reactions from `element`
                element = self._F.pop()
                logging.debug("Fast reactions from {:s}... ({:d} remaining in F)".format(
                    element, len(self._F)))

                # Return valid fast reactions:
                if self._p_loc:
                    reactions = self.get_limited_fast_reactions(element, self._p_loc)
                else :
                    reactions = self.get_fast_reactions(element)

                # Add new products to F
                new_products = self.get_new_products(reactions)
                self._F += (new_products)

                # Add new reactions to N_reactions
                N_reactions += (reactions)
                self._N.append(element)

                logging.debug("Generated {:d} new fast reactions.".format(len(reactions)))
                logging.debug("Generated {:d} new products.".format(len(new_products)))
                   
                # Display new reactions in interactive mode
                if self.interactive:
                    self.reactions_interactive(element, reactions, 'fast')


        except KeyboardInterrupt:
            logging.debug("Exiting neighborhood %s prematurely..." % source)

        logging.debug("In neighborhood %s..." % source)
        logging.debug("Segmenting %d complexes and %d reactions" %
                      (len(self._N), len(N_reactions)))

        # Now segment the neighborhood into transient and resting complexes
        # by finding the strongly connected components.
        segmented_neighborhood = segment_neighborhood(self._N, N_reactions, 
                                                      p_min=self._p_min)

        # TODO: check using sets instead
        # Resting complexes are added to S
        self._S += (segmented_neighborhood['resting_complexes'])

        # Transient complexes are added to T
        self._T += (segmented_neighborhood['transient_complexes'])

        # Resting macrostates are added to global list
        self._resting_macrostates += (segmented_neighborhood['resting_macrostates'])

        # Reactions from this neighborhood are added to the list
        self._reactions += (N_reactions)

        # Reset neighborhood
        logging.debug("Generated {:d} new fast reactions".format(len(N_reactions)))
        logging.debug("Generated {:d} new complexes: ({:d} transient, {:d} resting)".format(
            len(self._N), len(segmented_neighborhood['transient_complexes']), 
                len(segmented_neighborhood['resting_complexes'])))
        self._N = []

        logging.debug("Generated {:d} resting macrostates".format(
            len(segmented_neighborhood['resting_macrostates'])))
        logging.debug("Done processing neighborhood: {:s}".format(source))

    def get_slow_reactions(self, complex):
        """
        Returns a list of slow reactions possible using complex and other
        complexes in list E as reagents.

        This only supports unimolecular and bimolecular reactions. Could be
        extended to support arbitrary reactions.
        """

        maxsize = self._max_complex_size

        reactions = []

        # Do unimolecular reactions that are always slow... not supported
        # anymore...
        assert SLOW_REACTIONS[1] == []

        # Do unimolecular reactions that are sometimes slow
        for move in FAST_REACTIONS[1]:
            if move.__name__ == 'open':
                move_reactions = move(complex, 
                        max_helix=self._max_helix, 
                        release_11 = self._release_11,
                        release_1N = self._release_1N)
            else :
                move_reactions = move(complex, max_helix=self._max_helix, remote=self._remote)
            reactions += (r for r in move_reactions if self._k_fast > r.rate > self._k_slow)

        # Do bimolecular reactions
        for move in SLOW_REACTIONS[2]:
            reactions += (move(complex, complex))
            for complex2 in self._E:
                reactions += (move(complex, complex2))

        valid_reactions = []
        for rxn in reactions: 
            # It could be that k_slow is set, but k_fast is not....
            if maxsize and not all(p.size <= maxsize for p in rxn.products) :
                logging.warning(
                        "Product complex size (={}) larger than --max-complex-size(={}). Ignoring slow reaction {}!".format(max(map(lambda p: p.size, rxn.products)), maxsize, str(rxn)))
                continue
            valid_reactions.append(rxn)

        return valid_reactions

    def get_limited_fast_reactions(self, cplx, p_loc):
        """Accept/reject a fast reaction based on local elevation.

        Enumerates all fast reactions, then clusters them into compatible
        reactions. I.e. every pairwise combination of reactions is tested, if
        two or more reactions are compatible, they belong to the same clique.

        Local elevation is the inverse of the maximum free energy gain when
        applying a sequence of compatible moves.

        """
        reactions = self.get_fast_reactions(cplx)

        def rev_rtype(rtype, arity):
            """Returns the reaction type of a corresponding reverse reaction. """
            if rtype == 'open' and arity == (1,1):
                return 'bind11'
            elif rtype == 'open' and arity == (1,2):
                return 'bind21'
            elif rtype == 'bind11' or rtype == 'bind21':
                return 'open'
            elif rtype == 'branch-3way':
                return 'branch_3way'
            elif rtype == 'branch-4way':
                return 'branch_4way'

        def try_move(reactant, rtype, rotations, meta):
            (invader, target, x_linker, y_linker) = meta
            if rotations is not None and rotations != 0:
                invaders = map(lambda x: reactant.rotate_location(x, rotations), invader.locs)
                targets = map(lambda x: reactant.rotate_location(x, rotations), target.locs)
            else :
                invaders = list(invader.locs)
                targets = list(target.locs)

            assert len(invaders) == 1
            assert len(targets) == 1

            def triple(loc):
                return (reactant.get_domain(loc), reactant.get_structure(loc), loc)

            if rtype == 'bind11':
                results = reactlib.find_on_loop(reactant, invaders[0], 
                        reactlib.filter_bind11)
            elif rtype == 'branch-3way':
                results = reactlib.find_on_loop(reactant, invaders[0],
                        reactlib.filter_3way, direction = 1) + \
                          reactlib.find_on_loop(reactant, invaders[0], 
                        reactlib.filter_3way, direction = -1)
            elif rtype == 'branch-4way':
                results = reactlib.find_on_loop(reactant, invaders[0], 
                        reactlib.filter_4way)
            elif rtype == 'open':
                return reactant.get_structure(invaders[0]) == targets[0]
            else :
                raise Exception('unknown rtype:', rtype)

            targets = map(triple, targets)
            for [s,x,t,y] in results:
                if t == targets:
                    return True
            return False

        def elevation(rxn):
            assert rxn.arity == (1,1)
            if rxn.reverse_reaction is None:
                rr = rev_rtype(rxn.rtype, rxn.arity)
                r = self.get_fast_reactions(rxn.products[0], rtypes = [rr], restrict=False, rc=99)
                r = filter(lambda x: sorted(x.products) == sorted(rxn.reactants), r)
                assert len(r) == 1
                if len(r) == 1:
                    rxn.reverse_reaction = r[0]
                    r[0].reverse_reaction = rxn
                else :
                    rxn.reverse_reaction = False
            
            dG = math.log(rxn.rate/rxn.reverse_reaction.rate)
            return dG if dG > 0 else 0
        
        # Calculate the local elevation of a complex using only 1-1 reactions.
        compat = dict()
        for rxn in reactions:
            #print 'RXN', rxn, rxn.kernel_string, rxn.rtype
            if rxn.arity != (1,1): continue
            compat[rxn] = set()
            for other in reactions:
                if rxn == other: continue
                if other.arity != (1,1): continue
                #print 'OTH', other, other.kernel_string, other.rtype
                # Try to append the other reaction to this reaction
                success = try_move(rxn.products[0], other.rtype, rxn.rotations, other.meta)
                if success:
                    # We can apply other to the product of rxn
                    compat[rxn].add(other)

        # https://en.wikipedia.org/wiki/Clique_(graph_theory)
        cliques = []
        for p in sorted(compat):
            vert = p
            if compat[p] == set():
                cliques.append(set([p]))
                continue
            for l in list(compat[p]):
                edge = (p,l)
                processed = False
                for e, c in enumerate(cliques):
                    if p in c and (l in c or all(l in compat[y] for y in c)):
                        c.add(l)
                        processed = True
                if not processed:
                    cliques.append(set([p,l]))

        elevations = []
        for c in cliques:
            elevations.append(sum(map(elevation, c)))

        if elevations:
            eleven = max(elevations)
        else :
            eleven = 0

        #print cplx, cplx.kernel_string, eleven, math.e**(-eleven)

        filtered = []
        for rxn in reactions:
            if rxn.arity != (1,1):
                # we don't know the reverse rate, assuming uphill...
                if math.e**(-eleven) * rxn.rate < p_loc:
                    #print 'skipping', rxn, rxn.rtype, rxn.arity, math.e**(-eleven) * rxn.rate, p_loc
                    continue
            elif rxn.rate < rxn.reverse_reaction.rate:
                # this is a true uphill reaction...
                if math.e**(-eleven) * rxn.rate < p_loc:
                    #print 'skipping', rxn, rxn.rtype, rxn.arity, math.e**(-eleven) * rxn.rate, p_loc
                    continue
            else :
                #print 'accepting', rxn, rxn.rtype, rxn.arity, math.e**(-eleven) * rxn.rate
                pass
            filtered.append(rxn)

        return filtered

    def get_fast_reactions(self, cplx, rtypes = None, restrict=True, rc = None):
        """
        Returns a list of fast reactions possible using complex as a reagent.

        This only supports unimolecular reactions. Could be extended to support
        arbitrary reactions.
        """

        maxsize = self._max_complex_size

        reactions = []

        # Do unimolecular reactions
        for move in FAST_REACTIONS[1]:
            if rtypes and move.__name__ not in rtypes:
                continue
            if move.__name__ == 'open':
                if rc :
                    move_reactions = move(cplx, 
                        max_helix=self._max_helix, 
                        release_11 = rc,
                        release_1N = rc)
                else :
                    move_reactions = move(cplx, 
                        max_helix=self._max_helix, 
                        release_11 = self._release_11,
                        release_1N = self._release_1N)
            else :
                move_reactions = move(cplx, max_helix=self._max_helix, remote=self._remote)
            
            if not restrict: continue

            for rxn in move_reactions: 
                # It could be that k_slow is set, but k_fast is not....
                if rxn.rate >= max(self._k_fast, self._k_slow):
                    if maxsize and not all(p.size <= maxsize for p in rxn.products):
                        logging.warning("Product complex size (={}) larger than \
                        --max-complex-size(={}). Ignoring fast reaction {}!".format(
                            max(map(lambda p: p.size, rxn.products)), maxsize, str(rxn)))
                        continue
                    reactions.append(rxn)

        return reactions if restrict else move_reactions

    def get_new_products(self, reactions):
        """
        Checks the products in the list of reactions. Returns the new complexes in a list.

        """
        new_products = set()

        ESTNF = set(self._E + self._S + self._T + self._N + self._F)
        B = set(self._B)

        # Loop over every reaction
        for reaction in reactions:

            # Check every product of the reaction to see if it is new
            for (i, product) in enumerate(reaction.products):

                # This should have been checked earlier...
                assert product.size <= self._max_complex_size

                if product in B:
                    # If the product is in list B, then we need to remove it from
                    # that list so that it can be enumerated for self-interactions
                    # as part of this neighborhood
                    self._B.remove(product)
                    B.remove(product)

                # has not been enumerated...
                if product not in ESTNF:
                   new_products.add(product)

        assert (ESTNF - new_products) == ESTNF
        assert (ESTNF - B) == ESTNF

        return list(new_products)


def segment_neighborhood(complexes, reactions, p_min=None):
    """
    Segmentation of a potentially incomplete neighborhood. That means only
    the specified complexes are interesting, all others should not be
    returned.

    Beware: Complexes must contain all reactants in reactions *and* there
    must not be any incoming fast reactions into complexes, other than
    those specified in reactions. Thus, we can be sure that the SCCs found here
    are consistent with SCCs found in a previous iteration.

    Args:
        complexes(list[:obj:`PepperComplex`])
    """
    index = 0
    S = []
    SCCs = []

    total = complexes[:]
    for rxn in reactions: 
        total += rxn.products

    total = list(set(total))

    # Set up for Tarjan's algorithm
    for c in total: c._index = None

    # filters reaction products such that there are only species from within complexes
    # this is ok, because it must not change the assignment of SCCs.
    rxns_within = {k: [] for k in complexes}
    rxns_consuming = {k: [r for r in reactions if (k in r.reactants)] for k in total}
    for rxn in reactions:
        assert len(rxn.reactants) == 1
        for product in rxn.products:
            if product in complexes:
                rxns_within[rxn.reactants[0]].append(product)
        rxns_consuming[rxn.reactants[0]]

    def tarjans_scc(cplx, index):
        """
        Executes an iteration of Tarjan's algorithm (a modified DFS) starting
        at the given node.
        """
        # Set this node's tarjan numbers
        cplx._index = index
        cplx._lowlink = index
        index += 1
        S.append(cplx)

        for product in rxns_within[cplx]:
            # Product hasn't been traversed; recurse
            if product._index is None :
                index = tarjans_scc(product, index)
                cplx._lowlink = min(cplx._lowlink, product._lowlink)

            # Product is in the current neighborhood
            elif product in S:
                cplx._lowlink = min(cplx._lowlink, product._index)
    
        if cplx._lowlink == cplx._index:
            scc = []
            while True:
                next = S.pop()
                scc.append(next)
                if next == cplx:
                    break
            SCCs.append(scc)
        return index

    # We now perform Tarjan's algorithm, marking nodes as appropriate
    for cplx in complexes:
        if cplx._index is None:
            tarjans_scc(cplx, index)

    resting_macrostates = []
    transient_macrostates = []
    resting_complexes = []
    transient_complexes = []

    for scc in SCCs:
        try:
            ms = PepperMacrostate(scc[:], prefix='')
        except DSDDuplicationError, e:
            assert set(e.existing.complexes) == set(scc)
            ms = e.existing
        #except DSDObjectsError, e:
        #    assert set(e.existing.complexes) <= set(scc)
        #    del PepperMacrostate.MEMORY[e.existing.canonical_form]
        #    del PepperMacrostate.NAMES[e.existing.name]
        #    ms = PepperMacrostate(scc[:], prefix='')

        for c in scc:
            for rxn in rxns_consuming[c]:
                ms.add_reaction(rxn)

        if ms.is_transient:
            transient_complexes += (scc)
        else :
            resting_macrostates.append(ms)

            if p_min:
                for (c, s) in ms.get_stationary_distribution():
                    if s < p_min:
                        transient_complexes.append(c)
                    else :
                        resting_complexes.append(c)
            else:
                resting_complexes += (scc)

    resting_macrostates.sort()
    resting_complexes.sort()
    transient_complexes.sort()

    return {
        'resting_macrostates': resting_macrostates,
        'resting_complexes': resting_complexes,
        'transient_complexes': transient_complexes
    }

