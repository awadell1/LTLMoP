from CostSpec import AbstractCostSpec
import math
import re
from translateFromLTLMopLTLFormatToSlugsFormat import parseLTL
from translateFromLTLMopLTLFormatToSlugsFormat import parseSimpleFormula
from parseEnglishToLTL import bitEncoding, replaceRegionName
from specCompiler import SpecCompiler
from AbstractSyntaxTree import AbstractSyntaxTree, AtomicRegex, AtomicProp


class TwoDimensional(AbstractCostSpec):

    def write_cost_file(self, compiler):
        """ Generates *.cost file from the cost text supplied by the specification
        :param compiler: A parser
        :type compiler: SpecCompiler
        :return: None
        """

        costFile = open(self._cost_filename(), 'w')

        # Must use bit encoding with slugs
        assert self.proj.compile_options["use_region_bit_encoding"]

        # Regular Expressions used for parsing cost spec
        RE_FACTOR = re.compile('\d \d (<|>)', re.IGNORECASE)
        RE_ENTRY = re.compile('(\\d+\\.\\d+)\\s(.*)', re.IGNORECASE)

        # Step through Cost Specification
        costText = []
        for line in self.cost_text.split('\n'):
            # Check if First Line defines the Cost Factors for waiting and
            # delay costs
            if len(costText) == 0:
                if RE_FACTOR.search(line) is not None:
                    costText.append(line)
                    continue
                else:
                    RuntimeError('The first line of the cost spec must ' +
                                 'always represent the cost factors for' +
                                 'waiting and delay cost.')

            # Split each line into the value and formula portions
            entryRE = RE_ENTRY.search(line)
            value = entryRE.group(1)
            formula = entryRE.group(2)

            # Replace region names in cost with decomposed region names
            formula = compiler._subDecompedRegion(formula)

            # Replace Formula with bit encoding
            regionList = compiler.getRegionList()
            numBits = int(math.ceil(math.log(len(regionList), 2)))
            bitEncode = bitEncoding(len(regionList), numBits)
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
            costText.append(value + ' ' + str(formula))

        # Write costText to file
        costFile.write("\n".join(costText))

    def append_slugs_cmd(self, cmd):
        """
        Append SLUGS command to include twoDimensionalCost flag and
        the path to the generated *.cost file

        :param cmd: The current list of cmd arguments to pass to SLUGS
        :type cmd list
        :return: A updated list of cmd arguments to pass to SLUGS
        """

        # Activate the twoDimensionalCost Plug-in
        cmd.extend(['--twoDimensionalCost', self._cost_filename()])

        return cmd

    def append_internal_propositions(self, internal_props):
        """
        Define internal propositions used by the twoDimensionalCost plug-in
        :param internal_props: The current list of internal propositions
        :type internal_props: list
        :return: An update list of internal propositions
        """

        # Add in required internal propositions if not already added
        for p in [AtomicRegex(r'_l_a_c_v_\d'),
                  AtomicProp('_is_infty_cost_Pre'),
                  AtomicProp('_is_infty_cost_Post')]:
            if p not in internal_props:
                internal_props.append(p)

        return internal_props

    def _cost_filename(self):
        """
        :return: The filename for the cost specification file to pass to SLUGS
        """
        return self.proj.getFilenamePrefix() + '.cost'

    def _subDecompedRegion(self, fragment, prefix=""):
        """
        Replaces the names of regions with their decomposed versions
        :param fragment: An LTL formula
        :param prefix: Perpend region names with the prefix string
        :return: An LTL formula with region names replaced with by the
                 the decomposed name for each region
        """
        # substitute decomposed region names
        for r in self.proj.rfi.regions:
            # Only update region name if not an obstacle or the boundary region
            if not (r.isObstacle or r.isBoundary()):
                fragment = re.sub(prefix + r.name + '\\b',
                                  self.parser.proj.mappedRegion(r.name, "s."),
                                  fragment)

        return fragment
