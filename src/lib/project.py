#!/usr/bin/env python

""" ================================================
    project.py - Abstraction layer for project files
    ================================================

    This module exposes an object that allows for simplified loading of the
    various files included in a single project.
"""

# TODO: Document better

import os, sys
import fileMethods, regions
from numpy import *
import logging
import globalConfig
import re


class Project:
    """
    A project object.
    """

    def __init__(self):
        self.project_basename = None
        self.project_root = None
        self.spec_data = None
        self.silent = False
        self.regionMapping = None
        self.rfi = None
        self.specText = ""

        # -------- Two Dimensional Cost ------#
        self.hasCost = False
        self.costText = ""
        # ------------------------------------ #

        # -------- two_robot_negotiation ------#
        self.otherRobot = None
        # ------------------------------------ #

        self.all_sensors = []
        self.enabled_sensors = []
        self.all_actuators = []
        self.enabled_actuators = []
        self.all_customs = []
        self.internal_props = []
        self.current_config = ""
        self.shared_data = {}  # This is for storing things like server connection objects, etc.

        self.h_instance = {'init': {}, 'pose': None, 'locomotionCommand': None, 'motionControl': None, 'drive': None,
                           'sensor': {}, 'actuator': {}}

        # Compilation options (with defaults)
        self.compile_options = {"convexify": True,  # Decompose workspace into convex regions
                                "fastslow": False,  # Enable "fast-slow" synthesis algorithm
                                "symbolic": False,  # Use BDDs instead of explicit-state strategies
                                "decompose": True,
                                # Create regions for free space and region overlaps (required for Locative Preposition support)
                                "use_region_bit_encoding": True,
                                # Use a vector of "bitX" propositions to represent regions, for efficiency
                                "synthesizer": "jtlv",  # Name of synthesizer to use ("jtlv" or "slugs")
                                "optimal": "none",  # Method for applying cost to sythesis ("none" or "twoDim")
                                "parser": "structured"}  # Spec parser: SLURP ("slurp"), structured English ("structured"), or LTL ("ltl")

        self.ltlmop_root = globalConfig.get_ltlmop_root()

    def setSilent(self, silent):
        self.silent = silent

    def loadRegionMapping(self):
        """
        Takes the region mapping data and returns region mapping dictionary.
        """

        if self.spec_data is None:
            logging.error("Cannot load region mapping data before loading a spec file")
            return None

        try:
            mapping_data = self.spec_data['SPECIFICATION']['RegionMapping']
        except KeyError:
            logging.warning("Region mapping data undefined")
            return None

        if len(mapping_data) == 0:
            logging.warning("Region mapping data is empty")
            return None

        regionMapping = {}
        for line in mapping_data:
            oldRegionName, newRegionList = line.split('=')
            regionMapping[oldRegionName.strip()] = [n.strip() for n in newRegionList.split(',')]

        return regionMapping

    def loadRegionFile(self, decomposed=False):
        """
        Returns a Region File Interface object corresponding to the regions file referenced in the spec file
        """

        #### Load in the region file

        if decomposed:
            regf_name = self.getFilenamePrefix() + "_decomposed.regions"
        else:
            try:
                regf_name = os.path.join(self.project_root, self.spec_data['SETTINGS']['RegionFile'][0])
            except (IndexError, KeyError):
                logging.warning("Region file undefined")
                return None

        logging.info("Loading region file %s..." % regf_name)
        rfi = regions.RegionFileInterface()

        if not rfi.readFile(regf_name):
            if not self.silent:
                logging.error("Could not load region file %s!" % regf_name)
                if decomposed:
                    logging.error("Are you sure you compiled your specification?")
            return None

        logging.info("Found definitions for %d regions." % len(rfi.regions))

        return rfi

    def loadSpecFile(self, spec_file):
        # Figure out where we should be looking for files, based on the spec file name & location
        self.project_root = os.path.abspath(os.path.dirname(spec_file))
        self.project_basename, ext = os.path.splitext(os.path.basename(spec_file))

        # Load in the specification file
        logging.info("Loading specification file %s..." % spec_file)
        spec_data = fileMethods.readFromFile(spec_file)

        if spec_data is None:
            logging.warning("Failed to load specification file: %s" % spec_file)
            return None

        try:
            self.specText = '\n'.join(spec_data['SPECIFICATION']['Spec'])
        except KeyError:
            logging.warning("Specification text undefined")

        try:
            self.costText = '\n'.join(spec_data['SPECIFICATION']['Cost'])
            self.hasCost = True
        except KeyError:
            self.hasCost = False
            logging.warning("Cost text undefined")

        # ------ two_robot_negotiation ------#
        try:
            self.otherRobot = spec_data['SPECIFICATION']['OtherRobot']
        except KeyError:
            self.otherRobot = None
            logging.warning("Other robot undefinded")
        # ---------------------------------- #

        if 'CompileOptions' in spec_data['SETTINGS']:
            for l in spec_data['SETTINGS']['CompileOptions']:
                if ":" not in l:
                    continue

                k, v = l.split(":", 1)
                if k.strip().lower() in ("parser", "synthesizer", "optimal"):
                    self.compile_options[k.strip().lower()] = v.strip().lower()
                else:
                    # convert to boolean if not a parser type
                    self.compile_options[k.strip().lower()] = (v.strip().lower() in ['true', 't', '1'])

        # Add Internal Specs for Two Dimensional Cost
        #if self.compile_options["optimal"] == "twodim":
        #    self.internal_props.append("_l_a_c_v_1")
        #    self.internal_props.append("_is_infty_cost_Pre")

        return spec_data

    def writeSpecFile(self, filename=None):
        if filename is None:
            # Default to same filename as we loaded from
            filename = self.getFilenamePrefix() + ".spec"
        else:
            # Update the project path
            self.__setProjectPath(filename)

        data = {}

        # Create Dict of content to write to spec
        fullSpecText = {'Spec': self.specText}

        # Add Cost
        if self.hasCost:
            fullSpecText['Cost'] = self.costText

        # Add Other Robot
        if self.otherRobot is not None:
            fullSpecText['OtherRobot'] = self.otherRobot

        # Add Region Mapping
        if self.regionMapping is not None:
            fullSpecText['RegionMapping'] = [rname + " = " + ', '.join(rlist) for
                                             rname, rlist in self.regionMapping.iteritems()]

        # Add Full Specifications to Project
        data['SPECIFICATION'] = fullSpecText

        # Add Sensors, Actions and Custom Propositions to Project data
        data['SETTINGS'] = {"Sensors": [p + ", " + str(int(p in self.enabled_sensors)) for p in self.all_sensors],
                            "Actions": [p + ", " + str(int(p in self.enabled_actuators)) for p in self.all_actuators],
                            "Customs": self.all_customs}

        # Add Configuration Name to Project
        if self.current_config is not "":
            data['SETTINGS']['CurrentConfigName'] = self.current_config

        # Add Compilation Options to Project
        data['SETTINGS']['CompileOptions'] = "\n".join(
            ["%s: %s" % (k, str(v)) for k, v in self.compile_options.iteritems()])

        # Add Path to Region File
        if self.rfi is not None:
            # Save the path to the region file as relative to the spec file
            # FIXME: relpath has case sensitivity problems on OS X
            data['SETTINGS']['RegionFile'] = os.path.normpath(os.path.relpath(self.rfi.filename, self.project_root))

        # Set the Comments to be included with each section of the project file
        comments = {"FILE_HEADER": "This is a specification definition file for the LTLMoP toolkit.\n" +
                                   "Format details are described at the beginning of each section below.",
                    "RegionFile": "Relative path of region description file",
                    "Sensors": "List of sensor propositions and their state (enabled = 1, disabled = 0)",
                    "Actions": "List of action propositions and their state (enabled = 1, disabled = 0)",
                    "Customs": "List of custom propositions",
                    "Spec": "Specification in structured English",
                    "Cost": "Transistion Weights in structured English",
                    "OtherRobot": "The other robot in the same workspace",
                    "RegionMapping": "Mapping between region names and their decomposed counterparts"}

        # Write the Project data to the file
        fileMethods.writeToFile(filename, data, comments)

    def mappedRegion(self, regionName, prefix, orSymbol=' | '):
        """
        Returns an LTL fragment for the decomposed regions that are mapped to region
        :param regionName: The name of the region that was decomposed (str)
        :param prefix: The string to append the beginning of the region name
        :param orSymbol: the string used to represent the Or operator
        :return: LTL Fragment that is true iff in the region
        """

        return "(" + orSymbol.join([prefix + x for x in self.regionMapping[regionName]]) + ")"

    def loadProject(self, spec_file):
        """
        Because the spec_file contains references to all other project files, this is all we
        need to know in order to load everything in.
        """

        self.spec_data = self.loadSpecFile(spec_file)

        if self.spec_data is None:
            return False

        try:
            self.current_config = self.spec_data['SETTINGS']['CurrentConfigName'][0]
        except (KeyError, IndexError):
            logging.warning("No experiment configuration defined")

        self.regionMapping = self.loadRegionMapping()
        self.rfi = self.loadRegionFile()
        self.determineEnabledPropositions()

        return True

    def determineEnabledPropositions(self):
        """
        Populate lists ``all_sensors``, ``enabled_sensors``, etc.
        """

        # Figure out what sensors are enabled
        self.all_sensors = []
        self.enabled_sensors = []
        for line in self.spec_data['SETTINGS']['Sensors']:
            sensor, val = line.split(',')
            self.all_sensors.append(sensor.strip())
            if int(val) == 1:
                self.enabled_sensors.append(sensor.strip())

        # Figure out what actuators are enabled
        self.all_actuators = []
        self.enabled_actuators = []
        for line in self.spec_data['SETTINGS']['Actions']:
            act, val = line.split(',')
            self.all_actuators.append(act.strip())
            if int(val) == 1:
                self.enabled_actuators.append(act.strip())

        # Figure out what the custom propositions are
        self.all_customs = self.spec_data['SETTINGS']['Customs']

    def getFilenamePrefix(self):
        """ Returns the full path of most project files, minus the extension.

            For example, if the spec file of this project is ``/home/ltlmop/examples/test/test.spec``
            then this function will return ``/home/ltlmop/examples/test/test``
        """
        return os.path.join(self.project_root, self.project_basename)

    def getStrategyFilename(self):
        """ Returns the full path of the file that should contain the strategy
            for this specification. """

        return self.getFilenamePrefix() + ('.bdd' if self.compile_options["symbolic"] else '.aut')

    @property
    def specTextclean(self):
        """
        Returns the specification text with all comments and empty lines removed
        :return: A string of the clean specification
        """
        clean = []
        for line in self.spec_data['SPECIFICATION']['Spec']:
            if not line.startswith("#"):
                clean.append(line)

        return "\n".join(clean)

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

    def __setProjectPath(self, filename):
        """
        Set the project_basename and project_root based on the given filename
        :param filename: The filename of the *.spec file for the project
        """
        self.project_root = os.path.dirname(os.path.abspath(filename))
        self.project_basename, ext = os.path.splitext(os.path.basename(filename))
