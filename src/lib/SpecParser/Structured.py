from SpecParser import SpecParser
import parseEnglishToLTL
import re


class StructuredSpec(SpecParser):
    """
    A class for parsing structured english
    """

    def decompose(self):
        """
        Subsitute region names in the specification
        :return: The specification text with region names replaced
        """

        # Get a clean version of the specification
        specText = self.specTextclean

        if self.isDecompsed:
            # substitute the regions name in specs
            or_symbol = ' or '
            prefix = "s."
            for rA in self.regionNearIter:
                net_region = self.mappedRegion('near$' + rA + '$' + str(50), prefix, or_symbol)
                specText = re.sub(r'near (?P<rA>\w+)', net_region, specText)

            for rA, dist in self.regionWithinIter:
                net_region = self.mappedRegion('near$' + rA + '$' + dist, prefix, or_symbol)
                specText = re.sub(r'within ' + dist + ' (from|of) ' + rA, net_region, specText)

            for rA, rB in self.regionBetweenIter:
                net_region = self.mappedRegion('between$' + rA + '$and$' + rB + "$", prefix, or_symbol)
                specText = re.sub(r'between ' + rA + ' and ' + rB, net_region, specText)

            # Substitute decomposed region
            specText = self.subDecompedRegion(specText, '\\b')
        else:
            for r in self.rfi:
                if not (r.isObstacle or r.isBoundary()):
                    # TODO Replace with call to mappedRegion?
                    specText = re.sub('\\b' + r.name + '\\b', "s." + r.name, specText)
        return specText

    def parse(self):
        """
        Parse the raw specification text into the System and Environment LTL specification
        """

        # Replace region names with decomposed names
        specText = self.decompose()

        # Parse Structured LTL
        spec, traceback, failed, self._LTL2Spec, new_internal_props = \
            parseEnglishToLTL.writeSpec(specText, self.env_prop, self.rfi.regionList("s."), self.sys_prop)

        # Add new internal propositions
        self.addInternalProps(new_internal_props)

        return spec, traceback, failed

    @property
    def regionNearIter(self):
        """
        Returns an iterator over the all instances of "region near" in the specifcation
        :return: A iterator of type MatchObject with the region near in the "rA" group
        """
        regExp = r'near (?P<rA>\w+)'
        return iter(re.findall(regExp, self.specTextclean))

    @property
    def regionWithinIter(self):
        """
        Returns an iterator over the all instances of "within distance from a region" in the specifcation
        :return: A iterator of type MatchObject with the region within in the "rA" group and the distance
                in the "dist" group
        """
        regExp = r'within (?P<dist>\d+) (from|of) (?P<rA>\w+)'
        fullIter = re.findall(regExp, self.specTextclean)
        regionIter = []
        for rA, d, dist in fullIter:
            regionIter.append((rA, dist))

        return iter(regionIter)

    @property
    def regionBetweenIter(self):
        """
        Returns an iterator over all instances of "region between" in the specification
        :return: An iterator of type MatchObject with the two regions as the "rA" and "rB" groups
        """
        regExp = r'between (?P<rA>\w+) and (?P<rB>\w+)'
        return iter(re.findall(regExp, self.specTextclean))