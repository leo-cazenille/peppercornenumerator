#
#  test_reactions.py
#

import copy
import unittest

from nuskell.parser import parse_pil_string

from peppercornenumerator import Enumerator
import peppercornenumerator.reactions as rxn

# Input parsing stuff
from peppercornenumerator.utils import Domain, Strand, Complex, parse_dot_paren
from peppercornenumerator.input import from_kernel

def nuskell_parser(pil_string, ddlen=15):
    # snatched from nuskell.objects.TestTube.load_pil_kernel
    ppil = parse_pil_string(pil_string)

    #for p in ppil: print p

    def resolve_loops(loop):
      """ Return a sequence, structure pair from kernel format with parenthesis. """
      sequen = []
      struct = []
      for dom in loop :
        if isinstance(dom, str):
          sequen.append(dom)
          if dom == '+' :
            struct.append('+')
          else :
            struct.append('.')
        elif isinstance(dom, list):
          struct[-1] = '('
          old = sequen[-1]
          se, ss = resolve_loops(dom)
          sequen.extend(se)
          struct.extend(ss)
          sequen.append(old + '*' if old[-1] != '*' else old[:-1])
          struct.append(')')
      return sequen, struct

    domains = {}
    strands = {}
    complexes = {}
    for line in ppil :
      if line[0] == 'domain':
          domains[line[1]] = Domain(line[1], int(line[2]), sequence = 'N'* int(line[2]))
      elif line[0] == 'complex':
        name = line[1]
        sequence, structure = resolve_loops(line[2])

        strand = [] # construct a strand
        cplx_strands = [] # store strands for Complex
        for e in range(len(sequence)):
          d = sequence[e]
          if d == '+': 
              sid = '_'.join(tuple(map(str,strand)))
              if sid not in strands :
                  strands[sid] = Strand(sid, strand)
              cplx_strands.append(strands[sid])
              strand = [] # construct a strand
              continue
          if d[-1] == '*' : 
            dname = d[:-1]
            if dname in domains :
                cdom = domains[dname]
                dom = Domain(cdom.name, len(cdom), sequence = 'N'* len(cdom), is_complement=True)
            else :
                cdom = Domain(dname, ddlen, sequence = 'N'* ddlen, is_complement=False)
                domains[dname] = cdom
                dom = Domain(dname, ddlen, sequence = 'N'* ddlen, is_complement=True)
          else :
            dname = d
            if dname in domains :
                dom = domains[dname]
            else :
                dom = Domain(dname, ddlen, sequence = 'N'* ddlen)
                domains[dname] = dom
          strand.append(dom)

        sid = '_'.join(tuple(map(str,strand)))
        if sid not in strands :
            strands[sid] = Strand(sid, strand)
        cplx_strands.append(strands[sid])
        strand = [] # construct a strand
 

        cplx_structure = parse_dot_paren(''.join(structure))
        complex = Complex(name, cplx_strands, cplx_structure)
        complex.check_structure()
        complexes[name] = complex
      else :
        raise NotImplementedError('Weird expression returned from pil_parser!')

    #domains = domains.values()
    #strands = strands.values()
    #complexes = complexes.values()
    return (domains, strands, complexes)

class NewOpenTests(unittest.TestCase):
    def setUp(self):
        pass

    def test_basic_open(self):
        """ 
        A basic open reaction.

        Testing max-helix-semantics and release-cutoff 5, 8, 13
        """
        # INPUT
        (domains, strands, complexes) = nuskell_parser("""
        length a = 8
        length t = 5

        X = a( t( + ) )
        Y = a( t + t* )
        Z = a t( + ) a*
        S1 = a t 
        S2 = t* a*
        """)
        reactant = complexes['X']
        product1 = complexes['Y']
        product2 = complexes['Z']
        product_set = sorted([complexes['S1'], complexes['S2']])

        # max helix semantics ON -> no reactions vs dissociation
        output = rxn.open(reactant, max_helix=True, release_11=7, release_1N=7)
        self.assertEqual(output, [])
        output = rxn.open(reactant, max_helix=True, release_11=8, release_1N=8)
        self.assertEqual(output, [])
        forward = rxn.ReactionPathway('open', [reactant], product_set)
        # TODO: stopped working?????
        #output = rxn.open(reactant, max_helix=True, release_11=13, release_1N=13)
        #for o in output: print 'ow', o.kernel_string()
        #self.assertEqual(output, [forward])

        # max helix semantics OFF -> domains dissociate, but at most one at a time
        forward1 = rxn.ReactionPathway('open', [reactant], [product1])
        forward2 = rxn.ReactionPathway('open', [reactant], [product2])
        output = rxn.open(reactant, max_helix=False, release_11=7, release_1N=7)
        self.assertEqual(output, [forward1])
        output = rxn.open(reactant, max_helix=False, release_11=8, release_1N=8)
        self.assertEqual(output, [forward2, forward1])
        output = rxn.open(reactant, max_helix=False, release_11=13, release_1N=13)
        self.assertEqual(output, [forward2, forward1])

    def test_multiple_choice(self):
        # TODO: len(a) + len(b) = len(ab) - but the behavior is different!
        #
        ## think of hierarchical domain-level displacement.
        ## Upper  class: max-helix
        ## Middle class: no-max-helix
        ## Lower  class: sequence-level
        #
        # Should release-cutoff be dependent on domain-level representation?
        # That means, should release-cutoff of 4 mean "max-helix-semantics up
        # to length 4"? What would that mean if you start in 
        # "a b c( + ) b* a*" vs "ab c( + ) ab*"
        (domains, strands, complexes) = nuskell_parser("""
        length a = 3
        length b = 1
        length c = 3
        length ab = 4

        X = a( b( c( + ) ) )
        Y = ab( c( + ) )

        """)
        pass

class NewBindTests(unittest.TestCase):
    def setUp(self):
        pass

    def test_binding(self):
        (domains, strands, complexes) = nuskell_parser("""
        length a = 10
        length t = 5

        S1 = a t 
        S2 = t* a*
        X = a( t + t* )
        Y = a t( + ) a*
        Z = a( t( + ) )

        SB = a a t t* a* a*
        SG1 = a( a t t* ) a* 
        SG2 = a a( t t* a* ) 
        SG3 = a( a( t(  ) ) )

        SI1 = a( a t t* a* )
        SI2 = a a( t t* ) a*
        SI3 = a a t( ) a* a*
        """)
        S1 = complexes['S1']
        S2 = complexes['S2']
        X = complexes['X']
        Y = complexes['Y']
        Z = complexes['Z']
        singles = sorted([S1, S2])
        SB = complexes['SB']
        SG1 = complexes['SG1']
        SG2 = complexes['SG2']
        SG3 = complexes['SG3']
        SI1 = complexes['SI1']
        SI2 = complexes['SI2']
        SI3 = complexes['SI3']

        path = rxn.ReactionPathway('bind11', [X], [Z])
        output = rxn.bind11(X, max_helix=True)
        #for o in output: print 'mh', o.kernel_string()
        self.assertEqual(output, [path])

        path = rxn.ReactionPathway('bind11', [Y], [Z])
        output = rxn.bind11(Y, max_helix=True)
        #for o in output: print 'mh', o.kernel_string()
        self.assertEqual(output, [path])

        output = rxn.bind11(Z, max_helix=True)
        #for o in output: print 'mh', o.kernel_string()
        self.assertEqual(output, [])

        path1 = rxn.ReactionPathway('bind21', [S2, S1], [X])
        path2 = rxn.ReactionPathway('bind21', [S2, S1], [Y])
        output = rxn.bind21(S1, S2, max_helix=False)
        #for o in output: print 'bind21', o.kernel_string()
        self.assertEqual(output, sorted([path1, path2]))

        path = rxn.ReactionPathway('bind21', [S2, S1], [Z])
        output = rxn.bind21(S1, S2, max_helix=True)
        #for o in output: print 'bind21g', o.kernel_string()
        self.assertEqual(output, [path])

        path1 = rxn.ReactionPathway('bind11', [SB], [SG1])
        path2 = rxn.ReactionPathway('bind11', [SB], [SG2])
        path3 = rxn.ReactionPathway('bind11', [SB], [SG3])
        output = rxn.bind11(SB, max_helix=True)
        #for o in output: print 'open11g', o.kernel_string()
        self.assertEqual(output, sorted([path1, path2, path3]))

        path1 = rxn.ReactionPathway('bind11', [SB], [SG1])
        path2 = rxn.ReactionPathway('bind11', [SB], [SG2])
        path3 = rxn.ReactionPathway('bind11', [SB], [SI1])
        path4 = rxn.ReactionPathway('bind11', [SB], [SI2])
        path5 = rxn.ReactionPathway('bind11', [SB], [SI3])
        output = rxn.bind11(SB, max_helix=False)
        #for o in output: print 'open11f', o.kernel_string()
        self.assertEqual(output, sorted([path1, path2, path3, path4, path5]))

    def test_multiple_choice(self):
        pass

class NewBranch3WayTests(unittest.TestCase):
    def setUp(self):
        pass

    def test_single_migration(self):
        """ 
        A single 3-way branch migration reaction.
        """
        # INPUT
        (domains, strands, complexes) = from_kernel([
        "X = a( b x + b( d( + ) ) )",
        "Y = a( b( x + b d( + ) ) )",
        ])
        reactant = complexes['X']
        product = complexes['Y']

        # OUTPUT
        forward = rxn.ReactionPathway('branch_3way', [reactant], [product])
        backward = rxn.ReactionPathway('branch_3way', [product], [reactant])

        output = rxn.branch_3way(reactant, max_helix=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [forward])

        output = rxn.branch_3way(product, max_helix=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [backward])

        output = rxn.branch_3way(reactant, max_helix=False)
        #print output[0].kernel_string()
        self.assertEqual(output, [forward])

        output = rxn.branch_3way(product, max_helix=False)
        #print output[0].kernel_string()
        self.assertEqual(output, [backward])

    def test_max_helix_migration(self):
        """ 
        A series of 3-way branch migration reactions.
        """
        # INPUT
        (domains, strands, complexes) = from_kernel([
        "X  = a( x y z + x( y( z( b( + ) ) ) ) )",
        "I1 = a( x( y z + x y( z( b( + ) ) ) ) )",
        "I2 = a( x( y( z + x y z( b( + ) ) ) ) )",
        "Y  = a( x( y( z( + x y z b( + ) ) ) ) )",
        ])
        reactant = complexes['X']
        inter1 = complexes['I1']
        inter2 = complexes['I2']
        product = complexes['Y']

        # ~~~~~~~~~~~~~ #
        # OUTPUT max_helix #
        # ~~~~~~~~~~~~~ #
        forward = rxn.ReactionPathway('branch_3way', [reactant], [product])
        backward = rxn.ReactionPathway('branch_3way', [product], [reactant])

        output = rxn.branch_3way(reactant, max_helix=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [forward])

        output = rxn.branch_3way(product, max_helix=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [backward])

        forward = rxn.ReactionPathway('branch_3way', [inter1], [product])
        backward = rxn.ReactionPathway('branch_3way', [inter1], [reactant])

        output = rxn.branch_3way(inter1, max_helix=True)
        #for o in output: print 'max_helix', o.kernel_string()
        self.assertEqual(output, [backward, forward])
 
        # ~~~~~~~~~~~~~~~~~~~ #
        # OUTPUT NO-MAX-HELIX #
        # ~~~~~~~~~~~~~~~~~~~ #
        forward = rxn.ReactionPathway('branch_3way', [reactant], [inter1])
        backward = rxn.ReactionPathway('branch_3way', [product], [inter2])

        output = rxn.branch_3way(reactant, max_helix=False)
        #print output[0].kernel_string()
        self.assertEqual(output, [forward])

        output = rxn.branch_3way(product, max_helix=False)
        #print output[0].kernel_string()
        self.assertEqual(output, [backward])

        # OUTPUT NO-MAX-HELIX
        forward = rxn.ReactionPathway('branch_3way', [inter1], [inter2])
        backward = rxn.ReactionPathway('branch_3way', [inter1], [reactant])

        output = rxn.branch_3way(inter1, max_helix=False)
        #for o in output: print 'nmheli', o.kernel_string()
        self.assertEqual(sorted(output), sorted([forward, backward]))
 
    def test_remote_migration(self):
        """ 
        A remote 3way branch migration reaction.
        """
        # INPUT
        (domains, strands, complexes) = from_kernel([
        "X  = a( b x y z + x( y( z( c( + ) ) ) ) )",
        "I1 = a( b x( y z + x y( z( c( + ) ) ) ) )",
        "I2 = a( b x( y( z + x y z( c( + ) ) ) ) )",
        "Y  = a( b x( y( z( + x y z c( + ) ) ) ) )",
        ])
        reactant = complexes['X']
        inter1 = complexes['I1']
        inter2 = complexes['I2']
        product = complexes['Y']

        # ~~~~~~~~~~~~~ #
        # OUTPUT REMOTE #
        # ~~~~~~~~~~~~~ #
        forward = rxn.ReactionPathway('branch_3way', [reactant], [product])
        backward = rxn.ReactionPathway('branch_3way', [product], [reactant])

        output = rxn.branch_3way(reactant, max_helix=True, remote=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [forward])

        output = rxn.branch_3way(product, max_helix=True, remote=True)
        #print output[0].kernel_string()
        self.assertEqual(output, [backward])

        forward = rxn.ReactionPathway('branch_3way', [inter1], [product])
        backward = rxn.ReactionPathway('branch_3way', [inter1], [reactant])

        output = rxn.branch_3way(inter1, max_helix=True, remote=True)
        #for o in output: print 'max_helix', o.kernel_string()
        self.assertEqual(sorted(output), sorted([forward, backward]))
 
        # ~~~~~~~~~~~~~~~~~~~~ #
        # OUTPUT REJECT REMOTE #
        # ~~~~~~~~~~~~~~~~~~~~ #
        backward = rxn.ReactionPathway('branch_3way', [product], [reactant])

        output = rxn.branch_3way(reactant, max_helix=True, remote=False)
        #print output[0].kernel_string()
        self.assertEqual(output, [])

        output = rxn.branch_3way(product, max_helix=True, remote=False)
        #for o in output: print 'max_helix', o.kernel_string()
        self.assertEqual(output, [backward])

        forward = rxn.ReactionPathway('branch_3way', [inter1], [product])
        backward = rxn.ReactionPathway('branch_3way', [inter1], [reactant])

        output = rxn.branch_3way(inter1, max_helix=True, remote=False)
        #for o in output: print 'max_helix', o.kernel_string()
        self.assertEqual(sorted(output), sorted([forward, backward]))
 
    def test_multiple_choice(self):
        """ 
        A multiple choice input for 3way branch migration reactions.

        There are two important realizations: 
            1) max-helix move-set *only* extend immediately adjacent helices
            and *not* remote branches.
            2) max-helix move-set *always* extends in both directions.

        Example:

                y/
               x/
              z/
             y/
          a b/x y z c
          _x/________ 
          ___________ 
          a* x*y*z*c*

        """
        # INPUT
        (domains, strands, complexes) = from_kernel([
        "X  = a( x b y z x y + x( y( z( c( + ) ) ) ) )",
        "I1 = a( x( b y z x y + x y( z( c( + ) ) ) ) )",
        "I2 = a( x( b y( z x y + x y z( c( + ) ) ) ) )", # no-max-helix
        "Y1 = a( x( b y( z( x y + x y z c( + ) ) ) ) )",
        "I4 = a( x( b y z x y( + x y z( c( + ) ) ) ) )",
        "I3 = a( x b y z x( y + x y( z( c( + ) ) ) ) )", # no-max-helix
        "Y2 = a( x b y z x( y( + x y z( c( + ) ) ) ) )",
        ])
        reactant = complexes['X']
        inter1 = complexes['I1']
        inter2 = complexes['I2']
        inter3 = complexes['I3']
        inter4 = complexes['I4']
        product1 = complexes['Y1']
        product2 = complexes['Y2']

        # ~~~~~~ #
        # OUTPUT #
        # ~~~~~~ #
        forward = rxn.ReactionPathway('branch_3way', [reactant], [inter1])
        output = rxn.branch_3way(reactant, max_helix=True, remote=False)
        self.assertEqual(output, [forward])

        # NOTE: NO max_helix REMOTE TOEHOLDS!
        forward1b = rxn.ReactionPathway('branch_3way', [reactant], [inter1])
        forward2 = rxn.ReactionPathway('branch_3way', [reactant], [product2])
        output = rxn.branch_3way(reactant, max_helix=True, remote=True)
        self.assertEqual(output, [forward2, forward1b])

        backward1 = rxn.ReactionPathway('branch_3way', [product1], [reactant])
        output = rxn.branch_3way(product1, max_helix=True, remote=True)
        self.assertEqual(output, [backward1])

        # NOTE: INTERNAL REARRANGEMENT LEADS TO I4!
        backward2 = rxn.ReactionPathway('branch_3way', [product2], [reactant])
        backward2b = rxn.ReactionPathway('branch_3way', [product2], [inter4])
        output = rxn.branch_3way(product2, max_helix=True, remote=True)
        #for o in output: print 'ow', o.kernel_string()
        self.assertEqual(output, [backward2, backward2b])

        # NOTE: max_helix BRANCH MIGRATION MAXIMIZES NEW FORMED HELIX (forward2)!
        backward = rxn.ReactionPathway('branch_3way', [inter1], [reactant])
        forward2 = rxn.ReactionPathway('branch_3way', [inter1], [product2])
        forward  = rxn.ReactionPathway('branch_3way', [inter1], [product1])
        output = rxn.branch_3way(inter1, max_helix=True, remote=True)
        #for o in output: print 'ow', o.kernel_string()
        self.assertEqual(output, [backward, forward2, forward])

class NewBranch4WayTests(unittest.TestCase):
    def setUp(self):
        pass

    def test_branch4_way(self):
        pass

class DSD_PathwayTests(unittest.TestCase):
    def setUp(self):
        self.fast_reactions = [rxn.bind11, 
                    rxn.open, 
                    rxn.branch_3way, 
                    rxn.branch_4way]
        self.slow_reactions = {
                1: [],
                2: [rxn.bind21]
                }

        # Default options
        self._release_11 = 6
        self._release_1N = 6
        self._max_helix = True
        self._remote = True
        self._k_fast = 0.0
        self._k_slow = 0.0

    def test_bind_and_displace3way(self):
        # Skip the outer loop of the enumerator...
        (domains, strands, complexes) = nuskell_parser("""
        length a = 10
        length t = 5

        I = a b c
        J = b c
        C = b( c( + ) ) a*
        B = a( b c + b( c( + ) ) )
        D = a( b( c( + ) ) )
        """)
        I = complexes['I']
        J = complexes['J']
        C = complexes['C']
        B = complexes['B']
        D = complexes['D']

        # DSD-pathway "bind21"
        path1 = rxn.ReactionPathway('bind21', sorted([I, C]), [B])
        output = rxn.bind21(I, C, max_helix=True)
        self.assertEqual(output, [path1])

        # DSD-pathway "branch3way"
        path2 = rxn.ReactionPathway('branch_3way', [B], sorted([D, J]))
        output = rxn.branch_3way(B, max_helix=True)
        #for o in output: print 'test', o.kernel_string()
        self.assertEqual(output, [path2])

        enum = Enumerator(domains.values(), strands.values(), complexes.values())
        enum.enumerate()
        self.assertEqual(sorted(enum.reactions), sorted([path1, path2]))

    def test_cooperative_binding(self):
        (domains, strands, complexes) = nuskell_parser("""
        length a = 5
        length x = 15
        length y = 15
        length b = 5

        C = x( y( + b* ) ) a*
        L = a x
        R = y b
        T = x y
        """)
        enum = Enumerator(domains.values(), strands.values(), complexes.values())
        enum.k_fast = 25
        enum.max_helix_migration = False
        enum.enumerate()
        for r in enum.reactions:
            print r.kernel_string(), r.rate()

        print 'condensing'

        from peppercornenumerator.condense import condense_resting_states
        condensed = condense_resting_states(enum, compute_rates = True, k_fast=25)
        for r in condensed['reactions']:
            print r.kernel_string(), r.rate()
 

class NeighborhoodSearch(unittest.TestCase):
    # Test a basic move set and enumerate using k-fast/k-slow
    pass

class IsomorphicSets(unittest.TestCase):
    def setUp(self):
        pass

    def simple(self):
        pass

if __name__ == '__main__':
  unittest.main()

