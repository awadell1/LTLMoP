# Python 2
from abc import ABCMeta, abstractmethod
import re
from regions import RegionFileInterface
class SpecParser:
    __metaclass__ = ABCMeta
    # Dict for looking up line number from parsed LTL
    _LTL2Spec = dict()
    _internal_prop = []

    def __init__(self, specText, sys_prop, env_prop, rfi, regionMapping, isDecompsed):
        """
        Initialize a parser object
        :param specText: The unformatted specification
        :type specText: basestring

        :param: sys_prop: The system propositions
        :type sys_prop: list

        :param: env_prop: The environment propositions
        :type env_prop: list

        :param rfi: A region file interface object
        :type rfi: RegionFileInterface

        :param regionMapping: A dictionary mapping between decomposed region names
        :type regionMapping: dict

        :param isDecompsed: True iff the region have been decomposed
        :type isDecompsed: bool
        """
        self.rfi = rfi
        self.specTextRaw = specText
        self.sys_prop = sys_prop
        self.env_prop = env_prop
        self.regionMapping = regionMapping
        self.isDecompsed = isDecompsed

    @abstractmethod
    def decompose(self):
        """
        Subsitute region names in the specification
        :return: The specification text with region names replaced
        """
        return self.specTextRaw

    @abstractmethod
    def parse(self):
        """
        Parse the raw specification text into the System and Environment LTL specification
        :return (spec, traceback, failed)
        """

        return dict(), {}, True

    def reverseLookUp(self, LTL_fragment):
        """
        Returns the spec line number corresponding to the LTL fragment
        :param LTL_fragment: The LTL fragement to look up
        :type LTL_fragment: basestring
        :return: The line number of the LTL fragement or None if unable to match
        """
        return self._LTL2Spec[LTL_fragment]

    @property
    def specTextclean(self):
        """
        Returns the specification text with all comments and empty lines removed
        :return: A string of the clean specification
        """
        clean = []
        for line in self.specTextRaw.split("\n"):
            if not line.startswith("#"):
                clean.append(line)
        return "\n".join(clean)

    def mappedRegion(self, regionName, prefix, orSymbol=' | '):
        """
        Returns an LTL fragment for the decomposed regions that are mapped to region
        :param regionName: The name of the region that was decomposed (str)
        :param prefix: The string to append the beginning of the region name
        :param orSymbol: the string used to represent the Or operator
        :return: LTL Fragment that is true iff in the region
        """

        return "(" + orSymbol.join([prefix + x for x in self.regionMapping[regionName]]) + ")"

    def subDecompedRegion(self, fragment, prefix=""):
        """
        Replaces the names of regions with their decomposed versions
        :param fragment: The LTL fragment containing region names to be replaced
        :param prefix: Prepend name with prefix string when searching
        :return: The ltl fragment with all of the regions replace with their decomposed versions
        """
        # substitute decomposed region names
        for r in self.regionMapping.keys():
            fragment = re.sub(prefix + r + '\\b', self.mappedRegion(r, "s."), fragment)

        return fragment

    def addInternalProps(self, props):
        """
        Safely adds internal propositions
        :param props: A list of propositions to add
        :type props: list
        """
        for p in props:
            if p not in self._internal_prop:
                self._internal_prop.append(p)

    @property
    def internalProp(self):
        """
        :return: A List of interal properties
        """
        return self._internal_prop