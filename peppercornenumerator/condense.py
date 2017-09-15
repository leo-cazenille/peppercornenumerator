
import logging
import operator
import collections
import itertools as it
import numpy as np
from functools import reduce

from peppercornenumerator.objects import PepperComplex
from peppercornenumerator.objects import PepperReaction
from peppercornenumerator.objects import PepperRestingState
from peppercornenumerator.objects import DSDDuplicationError

class CondensationError(Exception):
    pass


class ReactionGraph(object):
    def __init__(self, enumerator):
        self._enumerator = enumerator

        # Condensed graph components
        self._SCCs = None
        self._set_to_fate = dict()
        self._complex_fates  = dict()
        self._condensed_reactions = None

        # Helper dictionaries
        self._scc_containing = None
        self._reactions_consuming = None

        # Condensed reaction rate calculations
        self._exit_probabilities = dict()
        self._stationary_distributions = dict()
        self._decay_probabilities = collections.defaultdict(float)
        self._reaction_decay_probabilities = collections.defaultdict(float)

    @property
    def enumerator(self):
        return self._enumerator

    @property
    def complexes(self):
        return self._enumerator.complexes

    @property
    def resting_states(self):
        if not self._set_to_fate:
            raise CondensationError('need to call condense first')
        return self._set_to_fate.values()

    @property
    def resting_state_representatives(self):
        if not self._set_to_fate:
            raise CondensationError('need to call condense first')
        return map(lambda x:x.canonical, self._set_to_fate.values())

    @property
    def set_to_fate(self):
        if not self._set_to_fate:
            raise CondensationError('need to call condense first')
        return self._set_to_fate

    @property
    def cplx_to_fate(self):
        if not self._complex_fates:
            raise CondensationError('need to call condense first')
        return self._complex_fates

    def reactions(self, condensed=False):
        if condensed :
            return self.condensed_reactions
        else :
            return self._enumerator.reactions

    @property
    def detailed_reactions(self):
        return self._enumerator.reactions

    @property
    def condensed_reactions(self):
        if self._condensed_reactions is None:
            self.condense()
        return list(self._condensed_reactions)

    @property
    def k_fast(self):
        return self._enumerator.k_fast

    def is_fast(self, rxn):
        return rxn.arity[0] == 1 and rxn.rate > self.k_fast

    def reactions_consuming(self, cplx):
        if self._reactions_consuming is None:
            self._reactions_consuming = get_reactions_consuming(self.complexes, self.reactions)
        return self._reactions_consuming[cplx]

    @property
    def SCCs(self):
        """
        Return (compute) a list of SCCs
        """
        if self._SCCs is None:
            if not self._reactions_consuming:
                self._reactions_consuming = get_reactions_consuming(
                        self.complexes, self.detailed_reactions)
            self._SCCs = tarjans(self.complexes, self.reactions, 
                    self._reactions_consuming, self.is_fast)
        return self._SCCs

    def SCC_containing(self, cplx):
        """ Map each complex to the SCC which contains the complex. 
        Each complex should be in 1 SCC.
        """
        if self._scc_containing is None:
            self._scc_containing = {c: scc for scc in self.SCCs for c in scc}
        return self._scc_containing[cplx]

    def calculate_reaction_decay_probabilities(self, rxn, fate, combinations=None):
        """
        Calculate the decay probability of a reaction to a particular fate.

            # each combination (`fates`) that sums to `fate` constitutes a
            # possible way this reaction can decay to `fate`, and therefore
            # contributes to P(r -> fate). This contribution is the joint
            # probability that each product `d` of r decays to the
            # corresponding fate `f` in `fates`.
        """
        if combinations is None:
            combinations = cartesian_product(map(self.get_fates, rxn.products))

        #print ''
        #print 'new', rxn
        #print 'be', fate 
        #print 'rp', rxn.products
        #print 'fs', combinations
        for fates in combinations :
            if tuple_sum_sort(fates) != fate:
                continue
            #print 'new-fates', fates
            #print 'products', rxn.products

            assert len(rxn.products) == len(fates)

            p = 1
            for (d, f) in zip(rxn.products, fates):
                #print 'dprob', d, f, self._decay_probabilities[(d, f)]
                p *= self._decay_probabilities[(d, f)]
            self._reaction_decay_probabilities[(rxn, fate)] += p

            #self._reaction_decay_probabilities[(rxn, fate)] += times(
            #        self._decay_probabilities[(d, f)] for (d, f) in zip(rxn.products, fates))
            #print 'new-result', self._reaction_decay_probabilities[(rxn, fate)]
            #print 'Pd', self._decay_probabilities

    def get_fates(self, cplx):
        if cplx not in self._complex_fates :
            self.compute_fates(self.SCC_containing(cplx))
        return self._complex_fates[cplx]

    def compute_fates(self, scc):
        """
        Processes a single SCC neighborhood, generating resting state multisets
        for each complex, and storing the mappings in the outer-scope
        `complex_fates` dict

        """
        #print 'computing fate', scc
        complex_fates = self._complex_fates

        if scc[0] in complex_fates:
            # Dirty check to see if the scc has been processed before.
            return 

        # Convert to a set for fast lookup
        scc_set = frozenset(scc)

        outgoing_reactions = []
        for c in scc:
            for r in self.reactions_consuming(c):
                if self.is_fast(r) and is_outgoing(r, scc_set) :
                    outgoing_reactions.append(r)

        # If this SCC is a resting state:
        if len(outgoing_reactions) == 0 :
            # build new resting state
            try :
                resting_state = PepperRestingState(scc)
            except DSDDuplicationError, e:
                resting_state = e.existing

            self._set_to_fate[scc_set] = resting_state

            # calculate stationary distribution
            self._stationary_distributions[resting_state] = self.get_stationary_distribution(scc)

            # assign fate to each complex in the SCC
            fate = (resting_state,) # needs to be iterable..
            fates = frozenset([fate])

            for c in scc:
                if c in complex_fates:
                    raise CondensationError('complex should not be assigned yet')
                # frozenset([ (get_resting_state(c),) ])
                complex_fates[c] = SetOfFates(fates)

                # all complexes in this SCC decay to this SCC with probability 1,
                # e.g. P(c -> SCC) = 1 for all c in this SCC
                self._decay_probabilities[(c, fate)] = 1.0
                #print 'setting decay prob to 1 for ', c, fate
            #print 'done with fate', scc, fate
            #print ''

        else :
            #print 'transient', scc
            # Compute all possible combinations of the fates of each product of r
            reaction_fate_combinations = [cartesian_product(
                map(self.get_fates, rxn.products)) for rxn in outgoing_reactions]

            #for i in range(len(reaction_fate_combinations)):
            #    print 'rxn', outgoing_reactions[i]
            #    print 'rfc', reaction_fate_combinations[i]

            # Compute the fates of each of the outgoing reactions by summing
            # each element above. Returns a list, with each element
            # corresponding to the frozenset of fates for one reaction.
            reaction_fates = [sorted(map(tuple_sum_sort, combination))
                              for combination in reaction_fate_combinations]
            
            # note that these two are equivalent; the intermediate
            # reaction_fate_combinations is only calculated for rates
            assert reaction_fates == [sorted(cartesian_sum(
                map(self.get_fates, rxn.products))) for rxn in outgoing_reactions]

            # calculate the exit probabilities
            self._exit_probabilities[scc_set] = self.get_exit_probabilities(scc)
            #print 'exit probabilities:', self._exit_probabilities[scc_set]

            # calculate the probability of each fate:
            # for each outgoing reaction, `r`
            #for f in reaction_fates:
            #    print 'n', f

            for (i, r) in enumerate(outgoing_reactions):
                #print i, r
                # for each possible `fate` of that reaction `r`
                for fate in reaction_fates[i]:
                    #print 'fate1', fate
                    # NOTE: this is weird, first you calculate the reaction decay
                    # probabilities from decay probabilities, then calculate decay
                    # probabilities from reaction decay probabilities?
                    fate = tuple(sorted(fate))
                    # calculate the probability that the products of `r`
                    # decay to `fate`, e.g. P(r -> fate)

                    # iterate over all combinations of the fates of `r`
                    # that sum to equal `fate`
                    combinations = reaction_fate_combinations[i]
                    #print 'combo', combinations
                    self.calculate_reaction_decay_probabilities(r, fate)#, combinations)

                    # the decay probability will be different for different
                    # complexes in the SCC
                    for c in scc:
                        # P(x decays to F) = P(SCC exits via r | SCC was entered via c) 
                        #   * P(r decays to F)
                        self._decay_probabilities[(c, fate)] += self._exit_probabilities[scc_set][
                                (c, r)] * self._reaction_decay_probabilities[(r, fate)]
                        #print 'dprob(c,f)', c, fate, self._decay_probabilities[(c, fate)]

            # The set of fates for the complexes in this SCC is the union of
            # the fates for all outgoing reactions.

            # Note that frozenset().union(*X) === X[0] U X[1] U X[2] ...
            # where X[i] is a frozenset and a U b represents the union of
            # frozensets a and b
            set_of_fates = frozenset().union(*reaction_fates)

            for c in scc:
                if c in complex_fates:
                    raise CondensationError('complex should not be assigned yet')
                complex_fates[c] = SetOfFates(set_of_fates)
            #print 'done with fate', scc, fate
            #print ''

    def get_resting_state(self, cplx):
        # get scc-containing
        raise NotImplementedError

    def condense(self):
        """
        Reaction condensation.
        """
        if self._condensed_reactions is not None:
            raise CondensationError('condensation called twice')
        else :
            self._condensed_reactions = set()

        enum = self.enumerator

        for scc in self.SCCs:
            self.compute_fates(scc)

        for reaction in enum.reactions :
            # NOTE: Fast reactions have been handled by the fates
            if self.is_fast(reaction):
                continue

            # Filter reactions with no products/reactants
            if len(reaction.reactants) == 0 and len(reaction.products) == 0:
                raise Exception('before we continue, see why that happens...')
                #continue

            # Get the corresponding fates (resting states)
            reactant_fates = map(self.get_fates, reaction.reactants)
            product_fates = map(self.get_fates, reaction.products)

            # Get all combinations of reactant and product fates,
            new_reactant_combinations = cartesian_sum(reactant_fates)
            new_product_combinations = cartesian_sum(product_fates)

            # Make sure each reactant is a resting state: 
            #   F(c) is a singleton for each reactant c
            for e, Fc in enumerate(reactant_fates):
                if not Fc.is_singleton() :
                    logging.error("Cannot condense reaction {}: ".format(reaction) + \
                            "reactant {} has multiple fates: F({}) = {}".format(
                                str(reaction.reactants[e]), str(reaction.reactants[e]), str(Fc)))
                    raise CondensationError()

            # Take all combinations of reactants and products
            new_reactant_product_combinations = it.product(
                    new_reactant_combinations, new_product_combinations)

            # Generate new reactions with each non-trivial combination
            for (reactants, products) in new_reactant_product_combinations:
                reactants = sorted(reactants)
                products = sorted(products)

                # skip the trivial case
                if reactants == products :
                    continue

                try :
                    reaction = PepperReaction(reactants, products, rtype='condensed')
                except DSDDuplicationError, e:
                    logging.debug('duplicating PepperReaction: {}'.format(e.existing))
                    reaction = e.existing

                reaction.rate = self.get_condensed_rate(reaction)
                self._condensed_reactions.add(reaction)
        return

    def get_condensed_rate(self, rxn):
        """

        Condensed rate from P + Q -> Fate
        
        Sum_{i,j,l} (p_i * q_j * K_{ij}^l * d^l(Fate)

        """
        reactants = tuple(rxn.reactants)
        products = tuple(rxn.products)

        # calculate_reaction_decay_probabilities
        # reaction_decay_probabilities

        # calculate reaction rate by summing over all representative detailed reactions
        detailed_reactions_consuming = set(
                [r for reactant in reactants 
                    for c in reactant.complexes 
                    for r in self.reactions_consuming(c)])

        reaction_rate = 0.0
        for r in detailed_reactions_consuming:
            # Calculate the probability that this detailed reaction decays to the products
            # P(r -> F), where F = products.
            self.calculate_reaction_decay_probabilities(r, products)

            #for x,y in self._reaction_decay_probabilities.items():
            #    print 'rdp', x, '=', y

            # probability that the products of this detailed reaction decay into fates
            # that yield the condensed reaction
            product_probability = self._reaction_decay_probabilities[(r, products)]
            assert product_probability >= 0

            # probability that the resting states comprising the reactants of
            # the condensed reaction will be in the right configuration to
            # perform the detailed reaction

            reactant_probabilities = times(self._stationary_distributions[self._set_to_fate[
                frozenset(self.SCC_containing(a))]][a] for a in r.reactants)

            #reactant_probabilities = 1
            #for a in r.reactants:
            #    fset = frozenset(self.SCC_containing(a))
            #    rset = self._set_to_fate[fset]
            #    reactant_probabilities *= self._stationary_distributions[rset][a]
            assert reactant_probabilities >= 0

            # rate of the detailed reaction
            k = r.rate
            assert k > 0

            #print 'r', reactant_probabilities
            #print 'k', k
            #print 'p', product_probability
            # overall contribution of detailed reaction r to rate of the condensed reaction 
            reaction_rate += reactant_probabilities * k * product_probability

            if isinstance(reaction_rate, complex):
                raise Exception
                if reaction_rate.imag > 0:
                    logging.warn("Detailed reaction {} contributes a complex rate of {} + {} " + \
                         " to condensed reaction {}.".format( 
                             r, reaction_rate.real, reaction_rate.imag, rxn))

        #print 'rate', rxn, reaction_rate
        return reaction_rate

    def get_stationary_distribution(self, scc):
        scc_set = frozenset(scc)
        scc_list = sorted(scc)
        L = len(scc)
    
        # assign a numerical index to each complex
        complex_indices = {c: i for (i, c) in enumerate(scc_list)}
    
        # find all reactions between complexes in this SCC (non-outgoing 1,1 reactions)
        reactions = [r for c in scc for r in self.reactions_consuming(c)
                     if (r.arity == (1, 1) and not is_outgoing(r, scc_set))]
    
        # T is the transition rate matrix, defined as follows:
        # T_{ij} = { rate(j -> i)       if  i != j
        #          { - sum_{j'} T_{j'i} if  i == j
        T = np.zeros((L, L))
    
        # add transition rates for each reaction to T
        for r in reactions:
            assert len(r.reactants) == 1
            assert len(r.products) == 1
            #raise SystemExit('stat-distr exit')
            # r : a -> b
            # T_{b,a} = rate(r : a -> b)
            a = r.reactants[0]
            b = r.products[0]
            T[complex_indices[b]][complex_indices[a]] = r.rate
    
        T0 = np.copy(T)
    
        # compute diagonal elements of T
        T_diag = np.sum(T, axis=0)  # sum over columns
        for i in xrange(L):
            T[i][i] = -T_diag[i]
    
        # calculate eigenvalues
        (w, v) = np.linalg.eig(T)
        # w is array of eigenvalues
        # v is array of eigenvectors, where column v[:,i] is eigenvector
        # corresponding to the eigenvalue w[i].
    
        # find eigenvector corresponding to eigenvalue zero (or nearly 0)
        epsilon = 1e-5
        i = np.argmin(np.abs(w))
        if abs(w[i]) > epsilon:
            logging.warn(
                ("Bad stationary distribution for resting state transition matrix. " +
                 "Eigenvalue found %f has magnitude greater than epsilon = %f. " +
                 "Markov chain may be periodic, or epsilon may be too high. Eigenvalues: %s") %
                (w(i), epsilon, str(w)))
        s = v[:, i]
    
        # check that the stationary distribution is good
        assert (s >= 0).all() or (s <= 0).all(), \
                "Stationary distribution of resting state complex " + \
                "should not be an eigenvector of mixed sign."
        s = s / np.sum(s)
        assert abs(np.sum(s) - 1) < epsilon, \
                "Stationary distribution of resting state complex " + \
                "should sum to 1 after normalization"
    
        # return dict mapping complexes to stationary probabilities
        return {c: s[i] for (c, i) in complex_indices.iteritems()}
    
    def get_exit_probabilities(self, scc):
        """
        """
        #print '\nEEEXIT: printr',scc
        # build set and list of elements in SCC; assign a numerical index to each complex
        scc_set = frozenset(scc)
        scc_list = sorted(scc)
        complex_indices = {c: i for (i, c) in enumerate(scc_list)}
    
        # find all fast reactions involving complexes in this SCC
        reactions = [r for c in scc for r in self.reactions_consuming(c) if self.is_fast(r)]
    
        # sort reactions into internal and outgoing; assign a numerical index to each reaction
        r_outgoing = sorted([r for r in reactions if is_outgoing(r, scc_set)])
        r_internal = sorted([r for r in reactions if not is_outgoing(r, scc_set)])
        exit_indices = {r: i for (i, r) in enumerate(r_outgoing)}
        #for r in r_internal: print 'int', r, r.rate
        #for r in r_outgoing: print 'out', r, r.rate
        #for k,v in exit_indices.items():
        #    print 'kv', k, v
    
        # L = # of complexes in SCC
        L = len(scc)
    
        # e = # of exit pathways
        e = len(r_outgoing)
    
        # add transition rates for each internal reaction
        T = np.zeros((L, L))
        for r in r_internal:
            assert len(r.reactants) == 1
            assert len(r.products) == 1
            a = r.reactants[0]
            b = r.products[0]
            T[complex_indices[a]][complex_indices[b]] = r.rate

        #print T
    
        # add transition rates for each outgoing reaction
        Te = np.zeros((L, e))
        for r in r_outgoing:
            a = r.reactants[0]
            Te[complex_indices[a]][exit_indices[r]] = r.rate
    
        #print Te
        # the full transition matrix P_{L+e x L+e} would be
        #
        # P = ( Q_{LxL}  R_{Lxe}   )
        #     ( 0_{exL}  I_{exe}   )
        #
        # but we really only care about Q to calculate the fundamental matrix,
        # so we construct
        #
        # P = (T_{LxL} Te_{Lxe})
        P = np.hstack((T, Te))
    
        # then normalize P along each row, to get the overall transition
        # probabilities, e.g. P_ij = P(i -> j), where i,j in 0...L+e
        P = P / np.sum(P, 1)[:, np.newaxis]
    
        # extract the interior transition probabilities (Q_{LxL})
        Q = P[:, 0:L]
    
        # extract the exit probabilities (R_{Lxe})
        R = P[:, L:L + e]
    
        # calculate the fundamental matrix (N = (I_L - Q)^-1)
        N = np.linalg.inv(np.eye(L) - Q)

        #print N
    
        # make sure all elements of fundamental matrix are >= 0
        if not (N >= 0).all() :  # --- commented out by EW (temporarily)
            raise CondensationError('negative elements in fundamental matrix')
    
        # calculate the absorption matrix (B = NR)
        B = np.dot(N, R)
    
        # --- added by EW as a weaker surrugate for the above, when necessary
        assert (B >= 0).all()
    
        # return dict mapping tuples of (incoming complex, outgoing reaction)
        # to exit probabilities
        #for (r, j) in exit_indices.iteritems():
        #    for (c, i) in complex_indices.iteritems():
        #        print "{}: {} = {}".format(c, r, B[i,j])
        #print {(c, r): B[i, j] for (c, i) in complex_indices.iteritems()
        #        for (r, j) in exit_indices.iteritems()}
        return {(c, r): B[i, j] for (c, i) in complex_indices.iteritems()
                for (r, j) in exit_indices.iteritems()}


class SetOfFates(object):
    """
    Corresponds to the set of multisets that can be reached from a given
    complex. Thin wrapper around the frozenset, mostly for prettier printing.
    """

    def __init__(self, states):
        # self._states = frozenset(states)
        self._states = frozenset([tuple(sorted(s)) for s in states])
        self._hash = None

    @property
    def states(self):
        return self._states

    def is_singleton(self):
        x = list(self._states)[0]
        return (len(self._states) == 1) and (len(x) == 1)

    def get_singleton(self):
        x = list(self._states)[0]
        return x[0]

    def __iter__(self):
        return iter(self.states)

    def __hash__(self):
        if(self._hash is None):
            self._hash = hash(self._states)
        return self._hash

    def __eq__(self, other):
        return sorted(list(self.states)) == sorted(list(other.states))

    def __str__(self):
        return "{ " + ", ".join(["{" + ", ".join(map(str, inner)) +
                                 "}" for inner in self.states]) + " }"

    def __len__(self):
        return len(self._states)

    def __repr__(self):
        return "SetOfFates([ " + ", ".join(
            ["(" + ", ".join(map(repr, inner)) + ")" for inner in self.states]) + " ])"


def is_outgoing(reaction, SCC_set):
    """
    Determines if the passed PepperReaction leads out of the passed SCC
    """
    if SCC_set is not set:
        SCC_set = set(SCC_set)

    # is subset of
    return not (set(reaction.products) <= SCC_set)


def times(iterable):
    """
    Multiplies each element of the given `iterable`, returns the product
    """
    return reduce(operator.mul, iterable)


def tuple_sum(iterable):
    """
    Given an iterable of tuples, concatenates each of the tuples
    and returns one big tuple. Precisely, for some list of tuples
    P = [p1, p2, p3 ...]::

        tuple_sum(P) = p1 + p2 + p3 + ...

    where + represents the concatenation of two tuples, e.g.
    (a1, a2) + (a3, a4) = (a1, a2, a3, a4).

    Example::

        tuple_sum([(1,2,3),(4,),(5,6)]) == (1, 2, 3, 4, 5, 6)

    """
    return reduce(operator.concat, tuple(iterable), tuple())


def tuple_sum_sort(iterable):
    return tuple_sort(tuple_sum(iterable))


def tuple_sort(tup):
    return tuple(sorted(tup))


def cartesian_product(iterable):
    """
    Gives the cartesian product of the passed `iterable`
    """
    # return map(tuple_sort, it.product(*iterable))
    return [tuple(x) for x in it.product(*iterable)]


def cartesian_sum(iterable):
    """
    Takes the cartesian sum over a set of multisets (counters). We define the
    cartesian sum X [+] Y between two sets X and Y as::

        X [+] Y = {x + y : x is in X and y is in Y}

    where + represents the sum of the multisets.

    Equivalently, in terms of the cartesian product X x Y, we can write X [+] Y as::

        X [+] Y = { (tuple_sum_{a in p} a) : p in X x Y }
    """
    # return map(tuple_sum,it.product(*iterable))
    return [tuple_sort(tuple_sum(x)) for x in cartesian_product(iterable)]


def get_reactions_consuming(complexes, reactions):
    """
    Returns a dict mapping each passed complex C to a list of reactions for which
    C is a reactant.
    """
    return dict((c, [r for r in reactions if (c in r.reactants)])
                for c in complexes)


def get_reactions_producing(complexes, reactions):
    """
    Returns a dict mapping each passed complex C to a list of reactions for which
    C is a product.
    """
    return dict((c, [r for r in reactions if (c in r.products)])
                for c in complexes)


def tarjans(complexes, reactions, reactions_consuming, is_fast):
    """
    Implementation of tarjans algorithm which segments SCCs of fast reactions
    """

    def strongconnect(complex, index):
        """
        Traverse a complex and all outgoing reactions
        """
        complex._index = index
        complex._lowlink = index
        # print "<"+str(complex)+" i='"+str(complex._index)+"'>"
        index += 1
        S.append(complex)

        for reaction in reactions_consuming[complex]:
            if (reaction.arity == (1, 1)) and is_fast(reaction):
                # if is_fast(reaction):
                # print '<rxn>' + repr(reaction) + '</rxn>'
                for product in reaction.products:

                    # Product hasn't been traversed; recurse
                    if(product._index is None):
                        index = strongconnect(product, index)
                        complex._lowlink = min(
                            product._lowlink, complex._lowlink)

                    # Product is in the current neighborhood
                    elif product in S:
                        complex._lowlink = min(product._index, complex._lowlink)
                # print "<ll
                # complex='"+str(complex)+"'>"+str(complex._lowlink)+"</ll>"

        if(complex._lowlink == complex._index):
            scc = []
            while(True):
                next = S.pop()
                scc.append(next)
                if(next == complex):
                    break

            SCCs.append(scc)
            # print "<scc>" + str(scc) + "</scc>"

        # print "<index i='"+str(index)+"' />"
        # print "</"+str(complex)+">"

        return index

    index = 0
    S = []
    SCCs = []

    # Just to make sure we don't try to access an undeclared property, initialize
    # all indicies to None
    for complex in complexes:
        complex._index = None

    # Outer loop ensures that no complexes get left behind by the DFS
    for complex in complexes:
        if(complex._index is None):
            index = strongconnect(complex, index)

    return SCCs


def condense_graph(enumerator, compute_rates=True, k_fast=0.0):
    """
    Condenses the reaction graph for the given `enumerator`.

    :param enumerator.Enumerator enumerator: The enumerator object to condense;
    `enumerate` must already have been called.  :param bool compute_rates: True
    to compute rates for the condensed reactions; requires numpy and slows
    calculation.

    Returns an object of the following form::

        {
            'resting_states': list of resting states
            'resting_state_map': dict mapping names to resting states,
            'resting_state_targets': dict mapping each complex to its fate,
            'condensed_reactions': list of PepperReaction objects representing the condensed reactions,
            'reactions': same as 'condensed_reactions'
         }

    """
    # Approach: compute SCCs using Tarjan's algorithm, including only fast
    # 1-1 reactions as edges. For each complex in the SCC, compute the
    # set of _fates_ of that complex (a fate is a multiset of resting states
    # that are reachable from that complex by fast reactions). For each
    # detailed reaction, generate one condensed reaction for each combination
    # of the fates of the products.
    #
    # Detailed description:
    # A fate of a complex is the multiset of resting states that can be reached
    # from the complex by a series of fast reactions. For instance, in the
    # network A -> B -> C, C -> D, D -> E + F where all reactions are fast,
    # there are three resting states: ^D = { D }, ^E = { E }, ^F = { F }, and
    # the complex A has two fates: { ^D } and { ^E, ^F }. We define F(x) for
    # some complex x to be the _set_ of fates of x; therefore
    # F(A) = { { ^D }, { ^E, ^F } }.
    #
    # Relatedly, for some reaction r = (A, (b1, b2, ...)) where A is the set of
    # reactants and B is the set of products, let the fate of the reaction
    # R(r) = F(b1) [+] F(b2) [+] ..., where [+] is the cartesian sum. Finally,
    # let S(x) be the SCC containing complex x. Note that S(x) may or may not
    # be a resting state.
    #
    # With these definitions, we can calculate F(x) by a recursion;
    #
    # F(x) = { { S(x) }            : if S(x) is a resting state
    #        { U_{r in R_o} R(r)   : if S(x) is not a resting state and R_o
    #                                represents the set of outgoing reactions
    #                                from S(x)
    #
    # Once we have calculated F(x) (which can be done by a DFS on the DAG formed
    # by the SCCs of the fast, detailed, 1-1 reactions---see the paper for
    # details on why this forms a DAG and therefore F(x) can be calculated in
    # finite time), the set of condensed reactions can be easily computed. We
    # generate one condensed reaction for each combination of fates of the
    # products.
    #
    # ------------------------------------------------------------------------

    # F(x) : Stores mapping between a complex x and the set of its possible fates
    complex_fates = {}

    # Stores mappings between an SCC and the associated resting state
    resting_states = {}

    # S(x) : Stores mappings between each complex x and the SCC S(x) which contains x
    SCC_containing = {}

    # Remembers which SCCs we've processed (those SCCs for which we've computed the fates)
    processed_SCCs = set()

    # The following dicts map SCCs to the various matrices used to
    # calculate the condensed reaction rates:

    # For resting state SCCs:
    # stationary_distributions[SCC] =  s^ : maps complexes to stationary probabilities
    stationary_distributions = {}

    # For transient SCCs:
    # exit_probabilities[SCC] = B : maps (incoming complex, outgoing reaction) tuples 
    # to exit probabilities
    exit_probabilities = {}

    # decay_probabilities[(x,F)] = P( x decays to F ) = P( x -> F ), where F is a fate of complex x
    decay_probabilities = collections.defaultdict(
        float)  # default to zero if no entry

    # reaction_decay_probabilities[(r,F)] = P( products of r decay to F ) = P( r -> F )
    # where F is a fate of reaction r
    reaction_decay_probabilities = collections.defaultdict(
        float)  # default to zero if no entry

    # Define helper functions for calculating condensed reaction rates
    def get_stationary_distribution(scc):
        scc_set = frozenset(scc)
        scc_list = sorted(scc)
        L = len(scc)

        # assign a numerical index to each complex
        complex_indices = {c: i for (i, c) in enumerate(scc_list)}

        # find all reactions between complexes in this SCC (non-outgoing 1,1
        # reactions)
        reactions = [r for c in scc for r in reactions_consuming[c]
                     if (r.arity == (1, 1) and not is_outgoing(r, scc_set))]


        # T is the transition rate matrix, defined as follows:
        # T_{ij} = { rate(j -> i)       if  i != j
        #          { - sum_{j'} T_{j'i} if  i == j
        T = np.zeros((L, L))

        # add transition rates for each reaction to T
        for r in reactions:
            # r : a -> b
            # T_{b,a} = rate(r : a -> b)
            a = r.reactants[0]
            b = r.products[0]
            T[complex_indices[b]][complex_indices[a]] = r.rate

        T0 = np.copy(T)

        # compute diagonal elements of T
        T_diag = np.sum(T, axis=0)  # sum over columns
        for i in xrange(L):
            T[i][i] = -T_diag[i]

        # calculate eigenvalues
        (w, v) = np.linalg.eig(T)
        # w is array of eigenvalues
        # v is array of eigenvectors, where column v[:,i] is eigenvector
        # corresponding to the eigenvalue w[i].

        # find eigenvector corresponding to eigenvalue zero (or nearly 0)
        epsilon = 1e-5
        i = np.argmin(np.abs(w))
        if abs(w[i]) > epsilon:
            logging.warn(
                ("Bad stationary distribution for resting state transition matrix. " +
                 "Eigenvalue found %f has magnitude greater than epsilon = %f. " +
                 "Markov chain may be periodic, or epsilon may be too high. Eigenvalues: %s") %
                (w(i), epsilon, str(w)))
        s = v[:, i]

        # check that the stationary distribution is good
        assert (s >= 0).all() or (s <= 0).all(), \
                "Stationary distribution of resting state complex should not be an eigenvector of mixed sign."
        s = s / np.sum(s)
        assert abs(np.sum(s) - 1) < epsilon, "Stationary distribution of resting state complex should sum to 1 after normalization"

        # return dict mapping complexes to stationary probabilities
        return {c: s[i] for (c, i) in complex_indices.iteritems()}

    def get_exit_probabilities(scc):
        # build set and list of elements in SCC; assign a numerical index to each complex
        scc_set = frozenset(scc)
        scc_list = sorted(scc)
        complex_indices = {c: i for (i, c) in enumerate(scc_list)}

        # find all fast reactions involving complexes in this SCC
        reactions = [r for c in scc for r in reactions_consuming[c] if is_fast(r)]

        # sort reactions into internal and outgoing; assign a numerical index to each reaction
        r_outgoing = sorted([r for r in reactions if is_outgoing(r, scc_set)])
        r_internal = sorted([r for r in reactions if not is_outgoing(r, scc_set)])
        exit_indices = {r: i for (i, r) in enumerate(r_outgoing)}

        # L = # of complexes in SCC
        L = len(scc)

        # e = # of exit pathways
        e = len(r_outgoing)

        # add transition rates for each internal reaction
        T = np.zeros((L, L))
        for r in r_internal:
            a = r.reactants[0]
            b = r.products[0]
            T[complex_indices[a]][complex_indices[b]] = r.rate

        # add transition rates for each outgoing reaction
        Te = np.zeros((L, e))
        for r in r_outgoing:
            a = r.reactants[0]
            Te[complex_indices[a]][exit_indices[r]] = r.rate

        # the full transition matrix P_{L+e x L+e} would be
        #
        # P = ( Q_{LxL}  R_{Lxe}   )
        #     ( 0_{exL}  I_{exe}   )
        #
        # but we really only care about Q to calculate the fundamental matrix,
        # so we construct
        #
        # P = (T_{LxL} Te_{Lxe})
        P = np.hstack((T, Te))

        # then normalize P along each row, to get the overall transition
        # probabilities, e.g. P_ij = P(i -> j), where i,j in 0...L+e
        P = P / np.sum(P, 1)[:, np.newaxis]

        # extract the interior transition probabilities (Q_{LxL})
        Q = P[:, 0:L]

        # extract the exit probabilities (R_{Lxe})
        R = P[:, L:L + e]

        # calculate the fundamental matrix (N = (I_L - Q)^-1)
        N = np.linalg.inv(np.eye(L) - Q)

        # make sure all elements of fundamental matrix are >= 0
        assert (N >= 0).all()   # --- commented out by EW (temporarily)

        # calculate the absorption matrix (B = NR)
        B = np.dot(N, R)

        # --- added by EW as a weaker surrugate for the above, when necessary
        assert (B >= 0).all()

        # return dict mapping tuples of (incoming complex, outgoing reaction)
        # to exit probabilities
        return {(c, r): B[i, j] for (c, i) in complex_indices.iteritems()
                for (r, j) in exit_indices.iteritems()}

    # Define helper functions
    def is_fast(reaction):
        """
        Current heuristic to determine if reaction is fast: unimolecular in reactants
        AND rate constant > k_fast
        """
        # return (reaction.arity == (1,1) or reaction.arity == (1,2)) and
        # reaction.rate > k_fast
        return (reaction.arity[0] == 1) and reaction.rate > k_fast

    def get_fates(complex):
        """
        Returns the set of possible fates for this complex, calling
        compute_fates if necessary
        """
        if(complex not in complex_fates):
            compute_fates(SCC_containing[complex])
        return complex_fates[complex]

    def get_resting_state(complex):
        """
        Returns the resting state associated with this complex, if
        one exists.
        """
        scc = SCC_containing[complex]
        scc_set = frozenset(scc)
        if(scc_set not in resting_states):
            compute_fates(scc)
        return resting_states[scc_set]

    def calculate_reaction_decay_probabilities(r, fate, combinations=None):
        if combinations is None:
            combinations = cartesian_product(map(get_fates, r.products))

        #print 'old', r, fate, combinations
        for fates in (combination for combination in combinations if tuple_sum(
                combination) == fate):
            #print 'old-fates', fates
            # each combination (`fates`) that sums to `fate`
            # constitutes a possible way this reaction can
            # decay to `fate`, and therefore contributes to
            # P(r -> fate). This contribution is the joint
            # probability that each product `d` of r decays to
            # the corresponding fate `f` in `fates`.
            reaction_decay_probabilities[(r, fate)] += times(
                    decay_probabilities[(d, f)] for (d, f) in zip(r.products, fates))
            #print 'old-result', reaction_decay_probabilities[(r, fate)]

    def compute_fates(scc):
        """
        Processes a single SCC neighborhood, generating resting state multisets
        for each complex, and storing the mappings in the outer-scope
        `complex_fates` dict
        """

        # Convert to a set for fast lookup
        scc_set = frozenset(scc)

        # Check that we haven't been here already
        if(scc_set in processed_SCCs):
            return

        outgoing_reactions = [
            r for c in scc for r in reactions_consuming[c] if (
                is_fast(r) and is_outgoing(
                    r, scc_set))]

        # Remember that we've processed this neighborhood
        processed_SCCs.add(scc_set)

        # If this SCC is a resting state:
        if(len(outgoing_reactions) == 0):

            # build new resting state
            try : #TODO check if that is a bug!
                resting_state = PepperRestingState(scc)
            except DSDDuplicationError, e:
                resting_state = e.existing

            resting_states[scc_set] = resting_state

            # calculate stationary distribution
            if compute_rates:
                stationary_distributions[resting_state] = get_stationary_distribution(
                    scc)

            # assign fate to each complex in the SCC
            fate = (resting_state,)
            fates = frozenset([fate])
            for c in scc:
                if c in complex_fates:
                    raise Exception()
                # frozenset([ (get_resting_state(c),) ])
                complex_fates[c] = fates

                # all complexes in this SCC decay to this SCC with probability 1,
                # e.g. P(c -> SCC) = 1 for all c in this SCC
                decay_probabilities[(c, fate)] = 1.0

        # Otherwise, if there are outgoing fast reactions:
        else:

            # Compute all possible combinations of the fates of each product of
            # r
            reaction_fate_combinations = [cartesian_product(
                map(get_fates, r.products)) for r in outgoing_reactions]
            #print 'ooo', reaction_fate_combinations 

            # Compute the fates of each of the outgoing reactions by summing each element above
            # This is a list, with each element corresponding to the frozenset
            # of fates for one reaction.
            reaction_fates = [sorted(map(tuple_sum_sort, combination))
                              for combination in reaction_fate_combinations]

            # note that these two are equivalent; the intermediate reaction_fate_combinations is only
            # calculated for the sake of the rates
            assert reaction_fates == [sorted(cartesian_sum(
                map(get_fates, r.products))) for r in outgoing_reactions]

            if compute_rates:
                # calculate the exit probabilities
                exit_probabilities[scc_set] = get_exit_probabilities(scc)

                # calculate the probability of each fate
                # for each outgoing reaction, `r`
                #for f in sorted(reaction_fates):
                #    print 'o', f
                for (i, r) in enumerate(outgoing_reactions):
                    # for each possible `fate` of that reaction `r`
                    for fate in reaction_fates[i]:

                        fate = tuple(sorted(fate))

                        # calculate the probability that the products of `r`
                        # decay to `fate`, e.g. P(r -> fate)

                        # not necessary since using defaultdict
                        # # initialize to zero
                        # if (r,fate) not in reaction_decay_probabilities:
                        #     reaction_decay_probabilities[(r,fate)] = 0

                        # iterate over all combinations of the fates of `r`
                        # that sum to equal `fate`

                        combinations = reaction_fate_combinations[i]
                        calculate_reaction_decay_probabilities(
                            r, fate, combinations)
                        # calculate_reaction_decay_probabilities(r,fate)

                        # the decay probability will be different for different
                        # complexes in the SCC
                        for c in scc:
                            # P(x decays to F) = P(SCC exits via r | SCC was
                            # entered via c) * P(r decays to F)

                            if (c, fate) not in decay_probabilities:
                                decay_probabilities[(c, fate)] = 0

                            decay_probabilities[(c,
                                fate)] += exit_probabilities[scc_set][(c,
                                    r)] * reaction_decay_probabilities[(r,
                                                                                                                            fate)]

            # The set of fates for the complexes in this SCC is the union of
            # the fates for all outgoing reactions.

            # Note that frozenset().union(*X) === X[0] U X[1] U X[2] ...
            # where X[i] is a frozenset and a U b represents the union of
            # frozensets a and b
            set_of_fates = frozenset().union(*reaction_fates)

            for c in scc:
                if c in complex_fates:
                    raise Exception()
                complex_fates[c] = set_of_fates

    # Cache some things for speed
    reactions_consuming = get_reactions_consuming(
        enumerator.complexes, enumerator.reactions)

    # Compute list of SCCs
    SCCs = tarjans(enumerator.complexes, enumerator.reactions,
                   reactions_consuming, is_fast)

    # Map each complex to the SCC which contains the complex (each complex should be in 1 SCC)
    SCC_containing.update({c: scc for scc in SCCs for c in scc})

    # Generate resting state multisets by processing each SCC. Outer loop
    # guarantees that all SCCs will be processed even if DFS recursion
    # misses some
    for scc in SCCs:
        compute_fates(scc)

    # Map each complex to the set of multisets of resting states which it can
    # reach
    complex_fates = {complex: SetOfFates(
        complex_fates[complex]) for complex in complex_fates}

    # Generate condensed reactions
    condensed_reactions = set()
    for reaction in enumerator.reactions:

        # Filter reactions which are fast (these have been handled by the fates)
        if(is_fast(reaction)):
            continue

        # Filter reactions with no products/reactants
        if (len(reaction.reactants) == 0) and (len(reaction.products) == 0):
            continue

        reactant_fates = map(get_fates, reaction.reactants)
        product_fates = map(get_fates, reaction.products)

        # Take cartesian sum of reactant fates
        new_reactant_combinations = cartesian_sum(reactant_fates)

        # Take cartesian sum of reaction product fates to get all
        # combinations of resting states
        new_product_combinations = cartesian_sum(product_fates)

        # make sure each reactant is a resting state (F(xn) is a singleton for each reactant xn)
        for (i, f_xn) in enumerate(reactant_fates):
            if(not f_xn.is_singleton()):
                logging.error(
                    "Cannot condense reaction %r: reactant %s has multiple fates: F(%s) = %s" %
                    (reaction, str( reaction.reactants[i]), str(
                        reaction.reactants[i]), str(f_xn)))
                raise Exception()

        # Now, we'll take all of the combinations of reactants and products
        new_reactant_product_combinations = it.product(
            new_reactant_combinations, new_product_combinations)

        # And generate new reactions with each combination which is not trivial
        # (reactants == products)
        for (reactants, products) in new_reactant_product_combinations:
            reactants = tuple(sorted(reactants))
            products = tuple(sorted(products))
            #print 'r', reactants
            #print 'p', products

            # Prune trivial reactions
            if(reactants != products):
                try :
                    reaction = PepperReaction(list(reactants), list(products), rtype='condensed')
                except DSDDuplicationError, e:
                    logging.debug('duplicating PepperReaction: {}'.format(e.existing))
                    reaction = e.existing

                if compute_rates:

                    # calculate reaction rate by summing over all
                    # representative detailed reactions
                    detailed_reactions_consuming = set(
                        [r for reactant in reactants for c in reactant.complexes for r in reactions_consuming[c]])
                    reaction_rate = 0.0
                    for r in detailed_reactions_consuming:

                        # calculate the probability that this detailed reaction decays to the products
                        # P(r -> F), where F = products. Used in next step
                        calculate_reaction_decay_probabilities(r, products)
                        #for x,y in reaction_decay_probabilities.items():
                        #    print 'o_rdp', x, '=', y

                        # probability that the products of this detailed reaction decay into fates
                        # that yield the condensed reaction
                        product_probability = reaction_decay_probabilities[(
                            r, products)]
                        assert product_probability >= 0

                        # probability that the resting states comprising the reactants of the condensed reaction will be in the right
                        # configuration to perform the detailed reaction
                        reactant_probabilities = times(stationary_distributions[resting_states[frozenset(
                            SCC_containing[a])]][a] for a in r.reactants)
                        assert reactant_probabilities >= 0

                        # rate of the detailed reaction
                        k = r.rate
                        assert k >= 0

                        # overall contribution of detailed reaction r to rate of the condensed reaction ^r =
                        # P(reactants of ^r are present as reactants of r) *
                        # k_r * P(products of r decay to products of ^r)
                        reaction_rate += reactant_probabilities * k * product_probability

                        if isinstance(reaction_rate, complex):
                            if reaction_rate.imag > 0:
                                logging.warn(
                                    ("Detailed reaction %s contributes a complex rate of %f + %fj " +
                                     " to condensed reaction %s.") %
                                    (r, reaction_rate.real, reaction_rate.imag, reaction))

                    #print 'o_r', reactant_probabilities
                    #print 'o_k', k
                    #print 'o_p', product_probability
                    #print 'rate_old', reaction_rate

                    reaction.rate = reaction_rate
                    #if reaction.rate == 0:
                    #    print reaction.full_string
                    #    raise Exception
                condensed_reactions.add(reaction)

    return {
        'resting_states': resting_states.values(),
        'resting_state_map': resting_states,
        'resting_state_targets': complex_fates,
        'condensed_reactions': list(condensed_reactions),
        'reactions': list(condensed_reactions),
        'complexes_to_resting_states': dict((c, rs) for rs in resting_states for c in rs)}


condense_resting_states = condense_graph
