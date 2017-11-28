from CostSpec import AbstractCostSpec
import math
import re
from translateFromLTLMopLTLFormatToSlugsFormat import parseLTL, parseSimpleFormula
from parseEnglishToLTL import bitEncoding, replaceRegionName
from specCompiler import SpecCompiler


class TwoDimensional(AbstractCostSpec):

    def write_cost_file(self, filename, compiler):
        """
        Generates *.cost file from the cost text supplied by the specification
        :param filename: The full filename for the *.cost file
        :type filename: str
        :param compiler: A parser
        :type compiler: SpecCompiler
        :return: None
        """

        costFile = open(filename, 'w')

        # Must use bit encoding with slugs
        assert self.proj.compile_options["use_region_bit_encoding"]

        regionList = compiler.getRegionList()

        # Create the region bit encoding
        numBits = int(math.ceil(math.log(len(regionList), 2)))
        bitEncode = bitEncoding(len(regionList), numBits)

        # Regex used for parsing cost spec
        RE_FACTOR = re.compile('\d \d (<|>)', re.IGNORECASE)
        RE_ENTRY = re.compile('(\\d+\\.\\d+)\\s(.*)', re.IGNORECASE)

        # Step through Cost Specification
        costText = []
        for line in self.cost_text.split('\n'):
            # Check if First Line -> Cost Factors
            if len(costText) == 0:
                if RE_FACTOR.search(line) is not None:
                    costText.append(line)
                    continue
                else:
                    RuntimeError("The first line of the cost spec must always represent the cost factors for waiting and delay cost.")

            # Split into the value and formula portions and check for success
            entryRE = RE_ENTRY.search(line)
            value = entryRE.group(1)
            formula = entryRE.group(2)

            # Replace region names in cost with decomposed region names
            formula = compiler._subDecompedRegion(formula)

            # Replace Formula with bit encoding
            formula = replaceRegionName(formula, bitEncode, regionList)

            # Replace Input (Sensor) names
            formula = self._replace_input_names(formula)

            # Replace Output (Actuator) names
            formula = self._replace_output_names(formula)

            # Parse into SLUGS format (Postfix notation)
            formulaTree = parseLTL(formula+';')
            formula = parseSimpleFormula(formulaTree[1], False)
            formula = ' '.join(formula)

            # Append to cost text
            costText.append(value + ' ' + formula)

        # Write costText to file
        costFile.write("\n".join(costText))

    def append_slugs_cmd(self, cmd):
        """
        Define to append options to when synthesizing a controller using SLUGS
        :param cmd: The current list of cmd arguments to pass to SLUGS
        :type cmd list
        :return: A updated list of cmd arguments to pass to SLUGS
        """

        # Activate the twoDimensionalCost Plugin
        cmd.extend(['--twoDimensionalCost', self.proj.getFilenamePrefix()+'.cost'])

        return cmd

    def append_internal_propositions(self, internal_props):
        """
        Define to append internal propositions to LTL specification
        :param internal_props: The current list of internal propositions
        :type internal_props: list
        :return: An update list of internal propositions
        """

        # Add in required internal propositions if not already added
        for p in ['_l_a_c_v_1', '_is_infty_cost_Pre']:
            if p not in internal_props:
                internal_props.append(p)

        return internal_props

    def _getRegionList(self):
        """
        Returns a list of region names from the parser.proj or self.proj depending on the setting of "decompose"
        :return: A list of region names
        """
        if self.proj.compile_options["decompose"]:
            regionList = self.parser.proj.rfi.regionList()
        else:
            regionList = self.proj.rfi.regionList()

        return regionList

    def _subDecompedRegion(self, fragment, prefix=""):
        """
        Replaces the names of regions with their decomposed versions
        :param fragment: The Ltl fragment conatining region names to be replaced
        :param prefix: Prepend name with prefix string when searching
        :return: The ltl fragement with all of the regions replace with their decomposed versions
        """
        # substitute decomposed region names
        for r in self.proj.rfi.regions:
            # Only update region name if not an obstacle or the boundary region
            if not (r.isObstacle or r.isBoundary()):
                fragment = re.sub(prefix + r.name + '\\b', self.parser.proj.mappedRegion(r.name, "s."), fragment)

        return fragment