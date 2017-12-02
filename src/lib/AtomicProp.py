import re


class AtomicProp(object):
    """
    A class for representing atomic propositions
    """
    def __init__(self, prop):
        self.prop_string = prop

    def __str__(self):
        return self.prop_string

    def __eq__(self, other):
        """
        Default to checking str(self) == str(other)
        :param other: An AtomicProp
        :return: true iff self is equivalent to the other proposition
        """
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.prop_string)

class AtomicRegex(AtomicProp):
    """
    A class for representing atomic propositions using regular expressions
    """

    def __init__(self, prop):
        """
        Initalize a Atomic Regex instance
        :param prop: The regular expression used to match other propositions
        """
        self.prop_string = prop
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