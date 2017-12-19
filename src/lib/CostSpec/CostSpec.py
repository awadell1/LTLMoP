class AbstractCostSpec(object):
    """
    DO NO INSTANTIATE
    Abstract class for incorporating cost annotations into the project class
    To create a new cost annotation subclass this class, modify existing
    methods as needed and add a new entry to loadCostSpec
    """
    def __init__(self, proj, cost_text):
        """
        Initialize the Cost Spec Class. To be called by subclasses via super
        :param proj: A Project Object
        :type proj: project.Project
        :param cost_text: The plain-text cost entry from a *.spec file
        :type cost_text:st
        """
        self.proj = proj
        self.cost_text = cost_text

    @classmethod
    def write_cost_file(self, filename, regionList):
        """
        Generates a *.cost file for the cost specifications.
        :param filename: The full filename for the *.cost file
        :type filename: str
        :return: None
        """
        pass

    @classmethod
    def append_slugs_cmd(self, cmd):
        """
        Define to append options to when synthesizing a controller using SLUGS
        :param cmd: The current list of cmd arguments to pass to SLUGS
        :type cmd list
        :return: A updated list of cmd arguments to pass to SLUGS
        """

        # Default to no additions
        return cmd

    @classmethod
    def append_internal_propositions(self, internal_props):
        """
        Define to append internal propositions to LTL specification.
        Internal propositions are propositions that are required for the
            execution of the automaton, but that should be hidden from the
            rest of the synthesis process.

        This method is expected to check for overlaps with existing
        propositions before adding to ensure all propositions are unique.
        This method is expected to NOT remove propositions from internal_props

        :param internal_props: The current list of internal propositions
        :type internal_props: list
        :return: An update list of internal propositions
        """

        # Default to no additions
        return internal_props

    def write_cost_spec(self):
        """
        Define to modify what is included in the cost section of the
        project's *.spec file. Defaults to the contents of self.cost_text

        The content of the cost section of the *.spec file is used reconstruct
        the CostSpec object when loading the project.

        :return: String to be written to the *.spec file to define the
                 cost specification
        """
        return self.cost_text

    def _replace_input_names(self, formula):
        """
        Prepends all input propositions with "e." in the formula
        :param formula: An LTL fragment
        :return: formula with all "inputProp" replaced with "e.inputProp"
        """
        for inProp in self.proj.all_sensors:
            formula = formula.replace(inProp, "e." + inProp)

        return formula

    def _replace_output_names(self, formula):
        """
        Prepends all output propositions with "s." in the formula
        :param formula: An LTL fragment
        :return: formula with all "outputProp" replaced with "s.outputProp"
        """
        for outProp in self.proj.all_actuators:
            formula = formula.replace(outProp, "s." + outProp)

        return formula


def loadCostSpec(cost_spec_name):
    """
    Returns the AbstractCostSpec subclass mapped to cost_spec_name
        cost_spec_name  SubClass        Usage
        'none'          NoCost          Default. No Cost annotation
        'twodim'        TwoDimensional  Cost Tuple representing the delay
                                        and transition cost of a transition

    :param cost_spec_name: The name of the CostSpec subclass
    :type cost_spec_name: str
    :return A AbstractCostSpec subclass
    """
    if cost_spec_name == 'none':
        from NoCost import NoCost
        return NoCost
    elif cost_spec_name == 'twodim':
        from TwoDimensional import TwoDimensional
        return TwoDimensional
