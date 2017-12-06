from translateFromLTLMopLTLFormatToSlugsFormat import tokenize, clean_tree
from parser import Parser
import re
import itertools
import math
from numpy import binary_repr
from copy import deepcopy


class AbstractSyntaxTree(object):
    """
    A class for representing an LTL formula as an abstract syntax tree
    """

    def __init__(self, formula='', notation='prefix'):
        """
        Creates an AbstractSyntaxTree (AST) to represent the given formula
        :param formula: The LTL Formula to represent
        """

        # Build a simple tree
        tokens = tokenize(formula + ';')
        p = Parser()
        simpleTree = clean_tree(p.parse(tokens))

        self.formula = self._parse(simpleTree)

        self.n_regions = None

        self.notation = notation

    def _notation_seq(self):
        if self.notation == 'prefix':
            seq = self.formula._prefix()
        elif self.notation == 'infix':
            seq = self.formula._infix()
        elif self.notation == 'postfix':
            seq = self.formula._postfix()
        return itertools.chain(seq)

    def __str__(self):
        str = []
        for op in self.__iter__():
            str.append(op.__str__())
        return ' '.join(str)

    def mark_region(self, region_list):
        # Replace AST_OP for region with AtomicRegions
        for r in self._region_prop():
            r_str = str(r)
            if r_str in region_list.keys():
                self.formula.replaceOp(r, AtomicRegion(r_str, region_list[r_str]))

        # Update the number of regions
        self.n_regions = len(region_list)

    def binary_encoding(self, reduce_formula=True):
        """
        Return a new AST that uses binary encoding
        :type reduce_formula: Distribute temporal operators over bits?
        """

        # Create a copy of the original tree
        btree = deepcopy(self)

        # Replace all instaces of AtomicRegion with their binary encoding
        for r in btree._region_prop():
            btree.formula.replaceOp(r, r.binary_formula(self.n_regions))

        # Distribute Temporal Operators
        if reduce_formula:
            btree.reduce()

        return btree

    def reduce(self):
        """
        Distribute temporal operators
        :return:
        """

        # Recursively distribute temporal operators
        self.formula.distribute()

    def _region_prop(self):
        """
        Return all instances of AtomicRegion in the formula
        """
        region_prop = []
        for p in self:
            if isinstance(p, AtomicRegion):
                region_prop.append(p)
        return region_prop

    @property
    def _region_set(self):
        """
        Return the set of all AtomicRegions used by the formula
        :return:
        """
        region_set = set()
        for p in self:
            if isinstance(p, AtomicRegion):
                region_set.add(p)
        return region_set

    def __iter__(self):
        if self.notation == 'prefix':
            seq = self.formula._prefix()
        elif self.notation == 'infix':
            seq = self.formula._infix()
        elif self.notation == 'postfix':
            seq = self.formula._postfix()
        else:
            raise ValueError
        return itertools.chain(seq)

    # Parse into AST
    def _parse(self, tree):
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
    """
    Class for representing a generic operation node
    """

    def __init__(self, symbol):
        """
        :param symbol: The symbol used to represent the operation
        :type symbol: str
        """
        self.symbol = symbol

    def __str__(self):
        return self.symbol

    def _postfix(self):
        return [self]

    def _prefix(self):
        return [self]

    def _infix(self):
        return [self]

    def replaceOp(self, target, new):
        return False

    def distribute(self):
        """
        Recursively distribute operators
        """
        raise NotImplementedError

class AST_Unary(AST_Op):
    """
    Class for representing a unary formula
    """

    def __init__(self, symbol, arg1):
        # type: (str, AST_Op) -> AST_Op
        super(AST_Unary, self).__init__(symbol)
        self.arg1 = arg1

    def _postfix(self):
        formula = self.arg1._postfix()
        formula.append(self)
        return formula

    def _prefix(self):
        formula = [self]
        formula.extend(self.arg1._prefix())
        return formula

    def _infix(self):
        return self._prefix()

    def replaceOp(self, target, new):
        if self.arg1 == target:
            self.arg1 = new
            return True
        return self.arg1.replaceOp(target, new)

    def distribute(self):
        """
        Recursively distribute operators
        :return:
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
        """
        Distribute Next Operator
        """

        # Distribute to sub arguments
        if isinstance(self.arg1, AtomicProp):
            self.arg1.sym_postfix = '\''
            self.arg1.use_postfix = True
        elif isinstance(self.arg1, AST_Unary):
            self.arg1 = NextOp(self.arg1.arg1)
        elif isinstance(self.arg1, AST_Binary):
            self.arg1.arg1 = NextOp(self.arg1.arg1)
            self.arg1.arg2 = NextOp(self.arg1.arg2)

        # Recursively distribute
        self.arg1 = self.arg1.distribute()

        # Replace self
        return self.arg1

class AST_Binary(AST_Op):
    """
    Class for representing a binary formula
    """

    def __init__(self, symbol, arg1, arg2):
        # type: (str, AST_Op, AST_Op) -> AST_Op
        super(AST_Binary, self).__init__(symbol)
        self.arg1 = arg1
        self.arg2 = arg2

    def _postfix(self):
        formula = self.arg1._postfix()
        formula.extend(self.arg2._postfix())
        formula.append(self)
        return formula

    def _prefix(self):
        formula = [self]
        formula.extend(self.arg1._prefix())
        formula.extend(self.arg2._prefix())
        return formula

    def _infix(self):
        formula = self.arg1._infix()
        formula.append(self)
        formula.extend(self.arg2._infix())
        return formula

    def replaceOp(self, target, new):
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
        """
        Recursively distribute operators
        :return:
        """
        self.arg1 = self.arg1.distribute()
        self.arg2 = self.arg2.distribute()
        return self

class AndOp(AST_Binary):
    def __init__(self, arg1, arg2=None):
        if arg2 is not None:
            a1 = arg1
            a2 = arg2
        elif len(arg1) > 2:
            a2 = arg1.pop()
            a1 = AndOp(arg1)
        elif len(arg1) == 2:
            a2 = arg1.pop()
            a1 = arg1.pop()
        else:
            raise IndexError
        super(AndOp, self).__init__('&', a1, a2)


class OrOp(AST_Binary):
    def __init__(self, arg1, arg2):
        super(OrOp, self).__init__('|', arg1, arg2)


class AtomicProp(AST_Op):
    """
    A class for representing atomic propositions
    """

    def __init__(self, prop, side=None):
        """
        Represents an atomic proposition
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
        str = self.symbol
        if self.use_prefix:
            str = self.sym_prefix + str
        if self.use_postfix:
            str = str + self.sym_postfix
        return str


    def __eq__(self, other):
        """
        Default to checking str(self) == str(other)
        :param other: An AtomicProp
        :return: true iff self is equivalent to the other proposition
        """
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.symbol)

    def distribute(self):
        """
        Distribution over AtomicPropsition is not possiable -> Return
        """
        return self

class AtomicRegex(AtomicProp):
    """
    A class for representing atomic propositions using regular expressions
    """

    def __init__(self, prop):
        """
        Initalize a Atomic Regex instance
        :param prop: The regular expression used to match other propositions
        """
        super(AtomicRegex, self).__init__(prop)
        self.regex = re.compile(prop)

    def __eq__(self, other):
        """
        :param other: An AtomicProp
        :return: True iff other is a match for self
        """

        if isinstance(other, AtomicRegex):
            # Equal if regex strings match
            return str(self) == str(other)
        else:
            # Equal if other is a match for the regex
            return self.regex.match(str(other)) is not None


class AtomicRegion(AtomicProp):
    def __init__(self, region, index=None):
        """
        An atomic proposition for representing a region
        :param region: The region name
        :type region: str
        :param index: The index (An 0,1,2,...) of the region. Defaults to None
        :type index: int
        """
        super(AtomicRegion, self).__init__(region, 'sys')

        # Fields for binary encoding
        self.index = index

    def binary_formula(self, n_regions):
        # type: (int) -> AST_Op
        """
        :param n_regions: The total number of regions
        :type n_regions: int
        :return: The binary AST formula for this AtomicRegion
        """

        # Validate Input
        if self.index is None: raise IndexError
        if self.index > n_regions: raise IndexError

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
    def __init__(self, props=[]):
        """
        Create a Set of props from props
        :param props: A set of propositions
        """
        self.prop_set = set(props)

    def __contains__(self, item):
        for p in self.prop_set:
            if p == item:
                return True
        return False
