from translateFromLTLMopLTLFormatToSlugsFormat import tokenize, clean_tree
from parser import Parser
import re
import itertools
import math
from numpy import binary_repr
from copy import deepcopy


class AbstractSyntaxTree(object):
    """
    A class for representing an LTL formula using abstract syntax trees
    """

    def __init__(self, formula='', notation='prefix'):
        """
        Creates an AbstractSyntaxTree (AST) to represent the given formula
        :param formula: The LTL Formula to represent
        :param notation: Notation to use when representing the formula as
                         a sting. Can be 'prefix', 'infix' or 'postfix'
        """

        # Build a simple tree from the LTL formula
        tokens = tokenize(formula + ';')
        p = Parser()
        simpleTree = clean_tree(p.parse(tokens))

        # Parse tree into an AST
        self.formula = self._parse(simpleTree)

        self.n_regions = None

        self.notation = notation

    def __str__(self):
        """ Returns the AST formula as a string"""
        str = []
        for op in self.__iter__():
            str.append(op.__str__())
        return ' '.join(str)

    def __iter__(self):
        """ Iterate over AST using current notation order"""
        if self.notation == 'prefix':
            seq = self.formula._prefix()
        elif self.notation == 'infix':
            seq = self.formula._infix()
        elif self.notation == 'postfix':
            seq = self.formula._postfix()
        else:
            raise ValueError
        return itertools.chain(seq)

    def mark_region(self, region_map):
        """ Replace AST_OP for regions with instances of AtomicRegion

            :param region_map A dictionary the maps region names to the
                              the index for each region.
                              ie. region_map['room1'] = 3
        """

        for r in self._region_prop():
            r_str = str(r)
            if r_str in region_map.keys():
                atomic_r = AtomicRegion(r_str, region_map[r_str])
                self.formula.replaceOp(r, atomic_r)

        # Update the number of regions
        self.n_regions = len(region_map)

    def binary_encoding(self, reduce_formula=True):
        """ Return a new AST that uses binary encoding for region

            :type reduce_formula: Distribute temporal operators over bits?
        """

        # Create a copy of the original AST
        btree = deepcopy(self)

        # Replace all instances of AtomicRegion with their binary encoding
        for r in btree._region_prop():
            btree.formula.replaceOp(r, r.binary_formula(self.n_regions))

        # Distribute Temporal Operators
        if reduce_formula:
            btree.reduce()

        return btree

    def reduce(self):
        """ Distribute Temporal Operators over Binary formulas.
            ie. N(r1 and r2) -> N(r1) and N(r2)
        """

        self.formula.distribute()

    def _region_prop(self):
        """ Return all instances of AtomicRegion in the formula """

        region_prop = []
        for p in self:
            if isinstance(p, AtomicRegion):
                region_prop.append(p)
        return region_prop

    @property
    def _region_set(self):
        """ Return the set of all AtomicRegions used by the formula """

        region_set = set()
        for p in self:
            if isinstance(p, AtomicRegion):
                region_set.add(p)
        return region_set

    # Parse into AST
    def _parse(self, tree):
        """ Recursively convert a tree returned by Parser into an AST """

        op = tree[0]
        if op == 'Formula':
            return self._parse(tree[1])
        elif op == 'Conjunction':
            return AndOp(self._parse(tree[1]), self._parse(tree[2]))
        elif op == 'UnaryFormula':
            binaryOp = tree[1][0]
            if binaryOp == 'NextOperator':
                return NextOp(self._parse(tree[2]))
            elif binaryOp == 'NotOperator':
                return NextOp(self._parse(tree[2]))
        elif op == 'Assignment':
            return AtomicRegion(tree[1])
        raise SyntaxError


class AST_Op(object):
    """ Base class for all nodes in an AST
    """

    def __init__(self, symbol):
        """ Initialize an AST_OP

        :param symbol: The symbol used to represent the operation
        :type symbol: str
        """
        self.symbol = symbol

    def __str__(self):
        """ The string representation of the AST_OP"""
        return self.symbol

    def _postfix(self):
        """ Return the postfix ordering for the AST_OP as a list """
        return [self]

    def _prefix(self):
        """ Return the prefix ordering for the AST_OP as a list """
        return [self]

    def _infix(self):
        """ Return the infix ordering for the AST_OP as a list """
        return [self]

    def replaceOp(self, target, new):
        """ Recursively replace an AST_OP in the AST

            :param target The AST_OP to replace
            :param new The AST_OP to replace target with

            AST_OP has no arguments to replace -> Return False
        """

        return False

    def distribute(self):
        """ Recursively distribute Temporal Operators over Binary formulas.
            ie. N(r1 and r2) -> N(r1) and N(r2)

            Default to returning self (Assume unable to distribute)
        """

        return self


class AST_Unary(AST_Op):
    """ Class for nodes representing an binary operator in an AST
    """

    def __init__(self, symbol, arg1):
        """ Initialize a binary operator
            :param symbol The symbol for the binary operator
            :param arg1 The first argument of the operator
        """

        super(AST_Unary, self).__init__(symbol)
        self.arg1 = arg1

    def _postfix(self):
        """ Return the postfix ordering as a list """

        formula = self.arg1._postfix()
        formula.append(self)
        return formula

    def _prefix(self):
        """ Return the prefix ordering as a list """

        formula = [self]
        formula.extend(self.arg1._prefix())
        return formula

    def _infix(self):
        """ Return the infix ordering as a list """

        formula = [self]
        formula.extend(self.arg1._prefix())
        return formula

    def replaceOp(self, target, new):
        """ Recursively replace an AST_OP in the AST

            :param target The AST_OP to replace
            :param new The AST_OP to replace target with

            Replace Unary argument if match otherwise recurse
        """

        if self.arg1 == target:
            self.arg1 = new
            return True
        return self.arg1.replaceOp(target, new)

    def distribute(self):
        """ Distribute Temporal Operators over Binary formulas.
            ie. N(r1 and r2) -> N(r1) and N(r2)
        """

        self.arg1 = self.arg1.distribute()
        return self


class NotOp(AST_Unary):
    def __init__(self, arg):
        super(NotOp, self).__init__('!', arg)


class NextOp(AST_Unary):
    def __init__(self, arg):
        super(NextOp, self).__init__('\'', arg)

    def distribute(self):
        """ Distribute the Next Operator over binary formulas """

        # Distribute to sub arguments
        if isinstance(self.arg1, AST_Unary):
            # Next(Op(arg)) -> Op(Next(arg))
            self.arg1 = NextOp(self.arg1.arg1)
        elif isinstance(self.arg1, AST_Binary):
            # Next(Op(arg1, arg2)) -> Op(Next(arg1), Next(arg2))
            self.arg1.arg1 = NextOp(self.arg1.arg1)
            self.arg1.arg2 = NextOp(self.arg1.arg2)

        # Recursively distribute
        self.arg1 = self.arg1.distribute()

        # Replace self
        return self.arg1


class AST_Binary(AST_Op):
    """ Class for nodes representing an binary operator in an AST
    """

    def __init__(self, symbol, arg1, arg2=None):
        """ Initialize a binary operator
            :param symbol The symbol for the binary operator

            Arguments can be pased either:
                Explicitly: Op(arg1, arg2)
                Implicitly: Op(arg[1], Op(arg[2], Op(arg[3],...)...)

            :param arg1 The first argument or a list of arguments
            :param arg2 The second argument for the operator or None
        """

        super(AST_Binary, self).__init__(symbol)

        if arg2 is not None:
            self.arg1 = arg1
            self.arg2 = arg2
        elif len(arg1) > 2:
            self.arg2 = arg1.pop()
            self.arg1 = AST_Binary(symbol, arg1)
        elif len(arg1) == 2:
            self.arg2 = arg1.pop()
            self.arg1 = arg1.pop()
        else:
            raise IndexError

    def _postfix(self):
        """ Return the prefix ordering as a list """

        formula = self.arg1._postfix()
        formula.extend(self.arg2._postfix())
        formula.append(self)
        return formula

    def _prefix(self):
        """ Return the prefix ordering as a list """

        formula = [self]
        formula.extend(self.arg1._prefix())
        formula.extend(self.arg2._prefix())
        return formula

    def _infix(self):
        """ Return the prefix ordering as a list """

        formula = self.arg1._infix()
        formula.append(self)
        formula.extend(self.arg2._infix())
        return formula

    def replaceOp(self, target, new):
        """ Recursively replace an AST_OP in the AST

            :param target The AST_OP to replace
            :param new The AST_OP to replace target with

            Replace if either arguments are a match, otherwise recurse
        """

        if self.arg1 == target:
            self.arg1 = new
            return True
        elif self.arg2 == target:
            self.arg2 = new
            return True
        elif not self.arg1.replaceOp(target, new):
            return self.arg2.replaceOp(target, new)
        else:
            return True

    def distribute(self):
        """ Distribute Temporal Operators over Binary formulas.
            ie. N(r1 and r2) -> N(r1) and N(r2)
        """

        self.arg1 = self.arg1.distribute()
        self.arg2 = self.arg2.distribute()
        return self


class AndOp(AST_Binary):
    """ Defines the Conjunction boolean operator """
    def __init__(self, arg1, arg2):
        super(AndOp, self).__init__('&', arg1, arg2)


class OrOp(AST_Binary):
    """ Defines the Disjunction boolean operator """
    def __init__(self, arg1, arg2):
        super(OrOp, self).__init__('|', arg1, arg2)


class AtomicProp(AST_Op):
    """ Class for nodes representing an atomic propositions in an ASTA class
    """

    def __init__(self, prop, side=None):
        """ Initialize an atomic proposition
        :param prop: The symbol for the proposition (ie. isSnow)
        :param side: Env, Sys or None -> Used to set the prefix if needed
        """

        super(AtomicProp, self).__init__(prop)

        # Set Symbol Prefix
        valid_prefix = {'env': 'e.', 'sys': 's.', None: ''}
        self.sym_prefix = valid_prefix[side]
        self.use_prefix = False

        # Set Symbol Postfix
        self.sym_postfix = ''
        self.use_postfix = False

    def __str__(self):
        """ The string representation of the AST_OP"""

        str = self.symbol
        if self.use_prefix:
            str = self.sym_prefix + str
        if self.use_postfix:
            str = str + self.sym_postfix
        return str

    def __eq__(self, other):
        """ True if self and other represent the same atomic proposition
            :param other: An AtomicProp
        """

        return str(self) == str(other)

    def __hash__(self):
        """ AtomicProps with the same symbol have the same hash """
        return hash(self.symbol)

    def distribute(self):
        """ Distribution over AtomicPropsition is not possible -> Return """
        return self


class AtomicRegex(AtomicProp):
    """ A class for representing atomic propositions using regular expressions
    """

    def __init__(self, prop):
        """ Initialize a Atomic Regex instance
        :param prop: The regular expression used to match other propositions
        """

        super(AtomicRegex, self).__init__(prop)
        self.regex = re.compile(prop)

    def __eq__(self, other):
        """ True if self and other represent the same atomic proposition
            :param other: An AtomicProp
        """

        if isinstance(other, AtomicRegex):
            # Equal if regex strings match
            return str(self) == str(other)
        else:
            # Equal if other is a match for this regex
            return self.regex.match(str(other)) is not None


class AtomicRegion(AtomicProp):
    """ A class for representing regions using atomic propositions
    """

    def __init__(self, region, index=None):
        """ An atomic proposition for representing a region
            :param region: The region name
            :type region: str
            :param index: The index (0,1,2,...) of the region. Defaults to None
            :type index: int
        """
        super(AtomicRegion, self).__init__(region, 'sys')

        # Fields for binary encoding
        self.index = index

    def binary_formula(self, n_regions):
        """ Return an AST for representing the region using binary encoding

            :param n_regions: The total number of regions
            :type n_regions: int
            :return: The binary AST formula for this AtomicRegion
        """

        # Validate Input
        if self.index is None:
            raise IndexError
        if self.index > n_regions:
            raise IndexError

        # Find number of bits needed
        num_bits = int(math.ceil(math.log(n_regions, 2)))

        # Expand to binary representation
        binary_rep = []
        for i, bit in enumerate(binary_repr(self.index, num_bits)):
            nextBit = AtomicProp('bit' + str(i), 'sys')
            if bit == '0':
                binary_rep.append(NotOp(nextBit))
            else:
                binary_rep.append(nextBit)

        # Return conjunction over all bit states
        return AndOp(binary_rep)


class AtomicPropSet(set):
    """ A Class for representing sets of AtomicPropositions """

    def __init__(self, props=[]):
        """ Initialize set from a list of props

            :param props: A list of propositions
        """
        self.prop_set = set(props)

    def __contains__(self, item):
        """ Checks if item is contained in the AtomicPropSet """

        for p in self.prop_set:
            if p == item:
                return True
        return False
