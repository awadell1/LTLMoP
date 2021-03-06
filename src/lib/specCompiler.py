import StringIO
import copy
import glob
import logging
import numpy
import globalConfig
import handlerSubsystem
import parseLP
import project
import regions
import strategy
from asyncProcesses import AsynchronousProcessThread
from cores.coreUtils import *
from createJTLVinput import createEnvTopologyFragment
from createJTLVinput import createEnvTopologyFragmentNoHeading
from createJTLVinput import createIAEnvActFragment
from createJTLVinput import createIAEnvTopologyFragment
from createJTLVinput import createIAInitialEnvRegionFragment
from createJTLVinput import createIAMaintainDistanceSysTopologyFragment
from createJTLVinput import createIASysPropImpliesEnvPropLivenessFragment
from createJTLVinput import createIASysTopologyFragment
from createJTLVinput import createInitialEnvRegionFragment
from createJTLVinput import createInitialRegionFragment
from createJTLVinput import createLTLfile
from createJTLVinput import createSMVfile
from createJTLVinput import createSysMutualExclusion
from createJTLVinput import createTopologyFragment
from parseEnglishToLTL import bitEncoding, replaceRegionName, createStayFormula

# logger for ltlmop
ltlmop_logger = logging.getLogger('ltlmop_logger')

# Hack needed to ensure there's only one
_SLURP_SPEC_GENERATOR = None


class SpecCompiler(object):
    def __init__(self, spec_filename=None):
        self.proj = project.Project()
        self.synthesis_subprocess = None

        if spec_filename is not None:
            self.loadSpec(spec_filename)

        # Set up SLUGS if needed
        self._setupSLUGS()

    def _setupSLUGS(self):
        """
        Asserts that SLUGS has been installed properly and adds slugs/tools to
        the python path if it has not already been added

        :raises Runtime Error if SLUGS has not been compiled
        :raises Runtime Error if ltlmop_root/etc/slugs/tools does not exist
        """

        if self.proj.compile_options["synthesizer"].lower() == "slugs":
            # Check that slugs was compiled
            slugs_path = os.path.join(self.proj.ltlmop_root,
                                      "etc", "slugs", "src", "slugs")

            if not os.path.exists(slugs_path):
                # TODO: automatically compile for the user
                raise RuntimeError(
                        "Please compile the synthesis code first. " +
                        "For instructions, see etc/slugs/README.md.")

            # Check that the slugs/tools folder exists
            slugs_tools_path = os.path.join(self.proj.ltlmop_root,
                                            "etc", "slugs", "tools")
            if not os.path.exists(slugs_tools_path):
                raise RuntimeError(
                        "Could not find the slugs/tools directory. " +
                        "Was SLUGS compiled correctly?")

            # Add the slugs/tools folder to the python path
            sys.path.insert(0, slugs_tools_path)

    def loadProject(self, p):
        """ Initalize specCompiler from a project object

            :param p: A instance of class project
            :return: This instance of class specComplier
        """

        # Check class of project
        assert(isinstance(p, project.Project))

        # Set p as the project
        self.proj = p

        # Return self for chaining
        return self

    def loadSpec(self, spec_filename):
        """
        Load the project object
        """
        self.proj.loadProject(spec_filename)

        # Check to make sure this project is complete
        if self.proj.rfi is None:
            ltlmop_logger.warning("Please define regions before compiling.")
            return

        # Remove comments
        self.specText = re.sub(r"#.*$", "",
                               self.proj.specText,
                               flags=re.MULTILINE)

        if self.specText.strip() == "":
            ltlmop_logger.warning(
                "Please write a specification before compiling.")
            return

        # Set up SLUGS if needed
        self._setupSLUGS()

    def loadSimpleSpec(self, text="", regionList=[], sensors=[], actuators=[], customs=[], adj=[], outputfile=""):
        """
        Load a simple spec given by the arguments without reading from a spec file

        For Slurp

        region, sensors, actuators, customs are lists of strings representing props
        adj is a list of tuples [(region1,region2),...]
        """

        if outputfile == "":
            ltlmop_logger.error("Need to specify output filename")
            return

        self.proj.compile_options['decompose'] = False
        self.proj.project_root = os.path.abspath(os.path.dirname(os.path.expanduser(outputfile)))
        self.proj.project_basename, ext = os.path.splitext(os.path.basename(outputfile))
        self.proj.specText=text
        # construct a list of region objects with given names
        self.proj.rfi = regions.RegionFileInterface()
        for rname in regionList:
            self.proj.rfi.regions.append(regions.Region(name=rname))

        self.proj.enabled_sensors = sensors
        self.proj.enabled_actuators = actuators
        self.proj.all_customs = customs

        # construct adjacency matrix
        self.proj.rfi.transitions= [[[] for j in range(len(self.proj.rfi.regions))] for i in range(len(self.proj.rfi.regions))]
        for tran in adj:
            idx0 = self.proj.rfi.indexOfRegionWithName(tran[0])
            idx1 = self.proj.rfi.indexOfRegionWithName(tran[1])
            self.proj.rfi.transitions[idx0][idx1] = [(0,0)] # fake trans face
            self.proj.rfi.transitions[idx1][idx0] = [(0,0)]

    def _decompose(self):
        """ Reliably rename regions and break-up regions as needed """

        # Parse the specfication
        self.parser = parseLP.parseLP()
        self.parser.main(self.proj.getFilenamePrefix() + ".spec")

        # Remove all references to any obstacle regions at this point
        for r in self.proj.rfi.regions:
            if r.isObstacle:
                # Delete corresponding decomposed regions
                for sub_r in self.parser.proj.regionMapping[r.name]:
                    index = self.parser.proj.rfi.indexOfRegionWithName(sub_r)
                    del self.parser.proj.rfi.regions[index]

                    # Remove decomposed region from any overlapping mappings
                    for k, v in self.parser.proj.regionMapping.iteritems():
                        if k == r.name:
                            continue
                        if sub_r in v:
                            v.remove(sub_r)

                # Remove mapping for the obstacle region
                del self.parser.proj.regionMapping[r.name]

        # Save the regions into new region file
        filename = self.proj.getFilenamePrefix() + '_decomposed.regions'

        # FIXME: properly support obstacles in non-decomposed maps?
        if self.proj.compile_options["decompose"]:
            self.parser.proj.rfi.recalcAdjacency()
            self.parser.proj.rfi.writeFile(filename)
            self.proj.regionMapping = self.parser.proj.regionMapping

        # Construct the *_decomposed.region files
        self.parser.proj.rfi.writeFile(filename)

        # Save project to *.spec file
        self.proj.regionMapping = self.parser.proj.regionMapping
        self.proj.writeSpecFile()

    def _writeSMVFile(self):
        """ Construct skelton SMV File from project """

        if self.proj.rfi:
            if self.proj.compile_options["decompose"]:
                numRegions = len(self.parser.proj.rfi.regions)
            else:
                numRegions = len(self.proj.rfi.regions)
        sensorList = self.proj.enabled_sensors
        robotPropList = self.proj.enabled_actuators + self.proj.all_customs

        if self.proj.rfi:
            # Add in regions as robot outputs
            if self.proj.compile_options["use_region_bit_encoding"]:
                robotPropList.extend(["bit"+str(i) for i in range(0,int(numpy.ceil(numpy.log2(numRegions))))])
                if self.proj.compile_options['fastslow']:
                    # remove _rc props from sensor_list and add in sbit for region completion
                    sensorList = [x for x in sensorList if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]
                    sensorList.extend(["sbit"+str(i) for i in range(0,int(numpy.ceil(numpy.log2(numRegions))))])
            else:
                if self.proj.compile_options["decompose"]:
                    robotPropList.extend([r.name for r in self.parser.proj.rfi.regions])
                    # added in region_rc with the decomposed region names
                    if self.proj.compile_options['fastslow']:
                        sensorList = [x for x in sensorList if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]
                        sensorList.extend([r.name+"_rc" for r in self.parser.proj.rfi.regions])
                else:
                    robotPropList.extend([r.name for r in self.proj.rfi.regions if r.name != 'boundary' and not r.isObstacle])
                    # added in region_rc with the original region names
                    if self.proj.compile_options['fastslow']:
                        sensorList = [x for x in sensorList if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]
                        sensorList.extend([r.name+"_rc" for r in self.proj.rfi.regions if r.name != 'boundary' and not r.isObstacle])

        self.propList = sensorList + robotPropList

        createSMVfile(self.proj.getFilenamePrefix(), sensorList, robotPropList)

    def _replaceInputNames(self, formula):
        """ Prepends all input propositions with "e." in the formala
            :param formula: An LTL fragment
            :return: formula with all "inputProp" replaced with "e.inputProp"
        """

        for inProp in self.proj.all_sensors:
            formula = formula.replace(inProp, "e."+ inProp)

        return formula

    def _replaceOutputNames(self, formula):
        """ Prepends all output propositions with "s." in the formala
            :param formula: An LTL fragement
            :return: formula with all "outputProp" replaced with "s.outputProp"
        """

        for outProp in self.proj.all_actuators:
            formula = formula.replace(outProp, "s."+ outProp)

        return formula

    def _writeLTLFile(self, createLTL = True):
        """ Construct *.ltl file from project """

        self.LTL2SpecLineNumber = None

        regionList = self.proj.rfi.regionList()
        sensorList = deepcopy(self.proj.enabled_sensors)
        actuatorList = deepcopy(self.proj.enabled_actuators)
        customsList = deepcopy(self.proj.all_customs)
        robotPropList = self.proj.enabled_actuators + self.proj.all_customs

        text = self.proj.specText

        response = None

        # Create LTL using selected parser
        # TODO: rename decomposition object to something other than 'parser'
        if self.proj.compile_options["parser"] == "slurp":
            # default to no region tags if no simconfig is defined, so we can compile without
            if self.proj.current_config == "":
                region_tags = {}
            else:
                self.hsub = handlerSubsystem.HandlerSubsystem(None, self.proj.project_root)
                config, success = self.hsub.loadConfigFile(self.proj.current_config)
                if success: self.hsub.configs.append(config)
                self.hsub.setExecutingConfig(self.proj.current_config)

                region_tags = self.hsub.executing_config.region_tags

            # Hack: We need to make sure there's only one of these
            global _SLURP_SPEC_GENERATOR

            # Make a new specgenerator and have it process the text
            if not _SLURP_SPEC_GENERATOR:
                # Add SLURP to path for import
                p = os.path.dirname(os.path.abspath(__file__))
                sys.path.append(os.path.join(p, "..", "etc", "SLURP"))
                from ltlbroom.specgeneration import SpecGenerator
                _SLURP_SPEC_GENERATOR = SpecGenerator()

            # Filter out regions it shouldn't know about
            filtered_regions = [region.name for region in self.proj.rfi.regions
                                if not (region.isObstacle or region.isBoundary())]
            LTLspec_env, LTLspec_sys, self.proj.internal_props, internal_sensors, results, responses, traceback = \
                _SLURP_SPEC_GENERATOR.generate(text, sensorList, filtered_regions, robotPropList, region_tags)

            oldspec_env = LTLspec_env
            oldspec_sys = LTLspec_sys

            for ln, result in enumerate(results):
                if not result:
                    ltlmop_logger.warning("Could not parse the sentence in line {0}".format(ln))

            # Abort compilation if there were any errors
            if not all(results):
                return None, None, responses

            # Add in the sensors so they go into the SMV and spec files
            for s in internal_sensors:
                if s not in sensorList:
                    sensorList.append(s)
                    self.proj.all_sensors.append(s)
                    self.proj.enabled_sensors.append(s)

            # Conjoin all the spec chunks
            LTLspec_env = '\t\t' + ' & \n\t\t'.join(LTLspec_env)
            LTLspec_sys = '\t\t' + ' & \n\t\t'.join(LTLspec_sys)

            if self.proj.compile_options["decompose"]:
                # substitute decomposed region names
                LTLspec_env = self._subDecompedRegion(LTLspec_env, '\\bs\.')
                LTLspec_env = self._subDecompedRegion(LTLspec_env, '\\bs\.')
                LTLspec_sys = self._subDecompedRegion(LTLspec_sys, '\\bs\.')
                LTLspec_sys = self._subDecompedRegion(LTLspec_sys, '\\bs\.')

            response = responses
        elif self.proj.compile_options["parser"] == "ltl":
            # delete comments
            text = re.sub(r"#.*$", "", text, flags=re.MULTILINE)

            # split into env and sys parts (by looking for a line of just dashes in between)
            LTLspec_env, LTLspec_sys = re.split(r"^\s*-+\s*$", text, maxsplit=1, flags=re.MULTILINE)

            # split into subformulas
            LTLspec_env = re.split(r"(?:[ \t]*[\n\r][ \t]*)+", LTLspec_env)
            LTLspec_sys = re.split(r"(?:[ \t]*[\n\r][ \t]*)+", LTLspec_sys)

            # remove any empty initial entries (HACK?)
            while '' in LTLspec_env:
                LTLspec_env.remove('')
            while '' in LTLspec_sys:
                LTLspec_sys.remove('')

            # automatically conjoin all the subformulas
            LTLspec_env = '\t\t' + ' & \n\t\t'.join(LTLspec_env)
            LTLspec_sys = '\t\t' + ' & \n\t\t'.join(LTLspec_sys)

            if self.proj.compile_options["decompose"]:
                # substitute decomposed region
                LTLspec_env = self._subDecompedRegion(LTLspec_env, '\\b(?:s\.)?')
                LTLspec_sys = self._subDecompedRegion(LTLspec_sys, '\\b(?:s\.)?')
            else:
                for r in self.proj.rfi.regions:
                    if not (r.isObstacle or r.isBoundary()):
                        LTLspec_env = re.sub('\\b(?:s\.)?' + r.name + '\\b', "s."+r.name, LTLspec_env)
                        LTLspec_sys = re.sub('\\b(?:s\.)?' + r.name + '\\b', "s."+r.name, LTLspec_sys)
                        LTLspec_env = re.sub('\\b(?:e\.)?' + r.name+"_rc" + '\\b' , "e."+r.name+"_rc", LTLspec_env)
                        LTLspec_sys = re.sub('\\b(?:e\.)?' + r.name+"_rc" + '\\b' , "e."+r.name+"_rc", LTLspec_sys)

            # HACK: needs to be something other than None
            traceback = []
        elif self.proj.compile_options["parser"] == "structured":
            import parseEnglishToLTL

            # Substitute the regions name in specs if decomposed
            if self.proj.compile_options["decompose"]:
                or_symbol = ' or '
                prefix = "s."
                for rA in self.proj.regionNearIter:
                    net_region = self.parser.proj.mappedRegion(
                                    'near$'+rA+'$' + str(50),
                                    prefix, or_symbol)
                    text = re.sub(r'near (?P<rA>\w+)', net_region, text)

                for rA, dist in self.proj.regionWithinIter:
                    net_region = self.parser.proj.mappedRegion(
                                    'near$'+rA+'$' + dist,
                                    prefix, or_symbol)
                    text = re.sub(r'within ' + dist + ' (from|of) ' + rA,
                                  net_region, text)

                for rA, rB in self.proj.regionBetweenIter:
                    net_region = self.parser.proj.mappedRegion(
                                    'between$'+rA+'$and$'+rB+"$",
                                    prefix, or_symbol)
                    text = re.sub(r'between ' + rA+' and ' + rB,
                                  net_region, text)

                # substitute decomposed region
                text = self._subDecompedRegion(text, '\\b')

                regionList = self.parser.proj.rfi.regionList("s.")
            else:
                for r in self.proj.rfi.regions:
                    if not (r.isObstacle or r.isBoundary()):
                        # TODO Replace with call to mappedRegion?
                        text = re.sub('\\b' + r.name + '\\b', "s."+r.name,
                                      text)

                regionList = self.proj.rfi.regionList("s.")

            # Parse English to LTL
            sensorList = deepcopy(self.proj.enabled_sensors)
            robotPropList = self.proj.enabled_actuators + self.proj.all_customs

            # Parse Structured English to LTL Specification
            spec, traceback, failed, self.LTL2SpecLineNumber, new_internal_prop = parseEnglishToLTL.writeSpec(
                text,
                sensorList,
                regionList,
                self.proj.enabled_actuators,
                self.proj.all_customs,
                fastslow=self.proj.compile_options['fastslow'],
                use_bits=self.proj.compile_options['use_region_bit_encoding']
                )

            # Append any truly new internal_props to the project
            for p in new_internal_prop:
                if p not in self.proj.internal_props:
                    self.proj.internal_props.append(p)

            # Abort compilation if there were any errors
            if failed:
                return None, None, None

            ################ Env Assumption Mining #############
            self.sensorList = sensorList
            self.regionList = regionList
            self.actuatorList = actuatorList
            self.customsList = customsList
            self.robotPropList = robotPropList
            if "TRUE" in spec["EnvInit"] :
                spec["EnvInit"] = "(TRUE)"

            # ---------- two_robot_negotiation ---------#
            spec['InitEnvRegionSanityCheck'] = ''
            spec['EnvTrans'] = spec['EnvTrans'].strip().rstrip('&') # all spec snippets has no trailing &
            spec['SysTrans'] = spec['SysTrans'].strip().rstrip('&') # all spec snippets has no trailing &

            if self.proj.rfi:
                if self.proj.compile_options['neighbour_robot']:
                    if self.proj.compile_options['include_heading']:
                        suffix = '_rc'
                        spec["EnvTrans"] = '&\n '.join(filter(None, [spec['EnvTrans'], createEnvTopologyFragment(self.proj.rfi.transitions, self.proj.rfi.regions, False, self.proj.otherRobot)]))
                    else:
                        spec["EnvTrans"] = '&\n '.join(filter(None, [spec['EnvTrans'], createEnvTopologyFragmentNoHeading(self.proj.rfi.transitions, self.proj.rfi.regions, False, self.proj.otherRobot)]))

                    for idx in range(len(self.proj.rfi.regions)):
                        # exclude boundary and obstacles
                        if self.proj.rfi.regions[idx].name == 'boundary' or self.proj.rfi.regions[idx].isObstacle:
                            continue
                        else:
                            for robot in self.proj.otherRobot:
                                if robot + '_' + self.proj.rfi.regions[idx].name not in self.proj.enabled_sensors:
                                    self.proj.enabled_sensors.append(robot + '_' + self.proj.rfi.regions[idx].name)
                                if robot + '_' + self.proj.rfi.regions[idx].name not in self.proj.all_sensors:
                                    self.proj.all_sensors.append(robot + '_' + self.proj.rfi.regions[idx].name)
                                if self.proj.compile_options['include_heading']:
                                    if robot + '_' + self.proj.rfi.regions[idx].name + suffix not in self.proj.enabled_sensors:
                                        self.proj.enabled_sensors.append(robot + '_' + self.proj.rfi.regions[idx].name + suffix)
                                    if robot + '_' + self.proj.rfi.regions[idx].name + suffix not in self.proj.all_sensors:
                                        self.proj.all_sensors.append(robot + '_' + self.proj.rfi.regions[idx].name + suffix)

                    # appending initial mutual exclusion to envInit
                    spec['InitEnvRegionSanityCheck'] = '&\n '.join(filter(None, [createInitialEnvRegionFragment(self.proj.rfi.regions, False, False, robot) for robot in self.proj.otherRobot]))
                    if self.proj.compile_options['include_heading']:
                        spec['InitEnvRegionSanityCheck'] = '&\n '.join(filter(None, [spec['InitEnvRegionSanityCheck']]+[createInitialEnvRegionFragment(self.proj.rfi.regions, False, False, robot, suffix) for robot in self.proj.otherRobot]))

                if self.proj.compile_options["fastslow"]:
                    if self.proj.compile_options["decompose"]:
                        spec['InitEnvRegionSanityCheck'] = '&\n '.join(filter(None, [spec['InitEnvRegionSanityCheck'], createIAInitialEnvRegionFragment(self.parser.proj.rfi.regions, use_bits=self.proj.compile_options["use_region_bit_encoding"])]))
                    else:
                        spec['InitEnvRegionSanityCheck'] = '&\n '.join(filter(None, [spec['InitEnvRegionSanityCheck'], createIAInitialEnvRegionFragment(self.proj.rfi.regions, use_bits=self.proj.compile_options["use_region_bit_encoding"])]))

                spec["EnvInit"] = '&\n '.join(filter(None, [spec["EnvInit"], spec['InitEnvRegionSanityCheck']]))
            else:
                spec['InitEnvRegionSanityCheck'] = None
                spec['SysInit'] = None

            if spec["SysInit"] == "()":
                spec["SysInit"] = "(TRUE)"     # not sure

            if self.proj.compile_options['neighbour_robot']:
                if self.proj.compile_options['decompose']:
                    # make sure the bits are mapped correctly with the use of self.parser
                    spec["SysTrans"] = '&\n '.join(filter(None,[spec['SysTrans']]+[createSysMutualExclusion(self.parser.proj.regionMapping, self.parser.proj.rfi.regions, self.proj.compile_options['use_region_bit_encoding'], robot, self.proj.compile_options['include_heading'], self.proj.compile_options['fastslow']) for robot in self.proj.otherRobot]))
                    spec["SysTrans"] = '&\n '.join(filter(None,[spec['SysTrans']]+[createSysMutualExclusion(self.parser.proj.regionMapping, self.parser.proj.rfi.regions, self.proj.compile_options['use_region_bit_encoding'], robot, self.proj.compile_options['include_heading'], False) for robot in self.proj.otherRobot]))

                else:
                    spec["SysTrans"] = '&\n '.join(filter(None,[spec["SysTrans"]]+[createSysMutualExclusion(self.parser.proj.regionMapping, self.proj.rfi.regions, self.proj.compile_options['use_region_bit_encoding'], robot, self.proj.compile_options['include_heading'], self.proj.compile_options['fastslow']) for robot in self.proj.otherRobot]))
                    spec["SysTrans"] = '&\n '.join(filter(None,[spec["SysTrans"]]+[createSysMutualExclusion(self.parser.proj.regionMapping, self.proj.rfi.regions, self.proj.compile_options['use_region_bit_encoding'], robot, self.proj.compile_options['include_heading'], False) for robot in self.proj.otherRobot]))

                if self.proj.compile_options['multi_robot_mode'] == 'd-patching' and False: #'charlie' in self.proj.project_root: (modified here)
                    if self.proj.compile_options['decompose']:
                        spec["SysTrans"] = '&\n '.join(filter(None,[spec['SysTrans']]+[createIAMaintainDistanceSysTopologyFragment(self.parser.proj.regionMapping, self.parser.proj.rfi.regions,\
                            self.parser.proj.rfi.transitions, use_bits=self.proj.compile_options['use_region_bit_encoding'], other_robot_names_list=self.proj.otherRobot)]))
                    else:
                        spec["SysTrans"] = '&\n '.join(filter(None,[spec['SysTrans']]+[createIAMaintainDistanceSysTopologyFragment(self.parser.proj.regionMapping, self.proj.rfi.regions,\
                            self.proj.rfi.transitions, use_bits=self.proj.compile_options['use_region_bit_encoding'], other_robot_names_list=self.proj.otherRobot)]))

           # --------------------------------------------#
            LTLspec_env = '&\n '.join(filter(None, [spec["EnvInit"], spec["EnvTrans"], spec["EnvGoals"]]))
            LTLspec_sys = '&\n '.join(filter(None, [spec["SysInit"], spec["SysTrans"], spec["SysGoals"]]))
            ####################################################
        else:
            ltlmop_logger.error("Parser type '{0}' not currently supported".format(self.proj.compile_options["parser"]))
            return None, None, None

        if self.proj.rfi:
            if self.proj.compile_options["decompose"]:
                regionList = [x.name for x in self.parser.proj.rfi.regions]
                regionListCompleted = [
                    x.name+"_rc" for x in self.parser.proj.rfi.regions]
            else:
                regionList = [x.name for x in self.proj.rfi.regions]
                regionListCompleted = [
                    x.name+"_rc" for x in self.proj.rfi.regions]

            if self.proj.compile_options["use_region_bit_encoding"]:
                # Define the number of bits needed to encode the regions
                numBits = int(math.ceil(math.log(len(regionList), 2)))
                # creating the region bit encoding
                bitEncode = bitEncoding(len(regionList), numBits)

                # switch to bit encodings for regions
                LTLspec_env = replaceRegionName(LTLspec_env,
                                                bitEncode,
                                                regionList)

                LTLspec_sys = replaceRegionName(LTLspec_sys,
                                                bitEncode,
                                                regionList)

                # Update LTL -> Spec Mapping
                if self.LTL2SpecLineNumber is not None:
                    for k in self.LTL2SpecLineNumber.keys():
                        new_k = replaceRegionName(k, bitEncode, regionList)
                        if new_k != k:
                            self.LTL2SpecLineNumber[new_k] = self.LTL2SpecLineNumber[k]
                            del self.LTL2SpecLineNumber[k]

            # Select correct adjacency data
            if self.proj.compile_options["decompose"]:
                adjData = self.parser.proj.rfi.transitions
            else:
                adjData = self.proj.rfi.transitions

        # Store some data needed for later analysis
        self.spec = spec
        use_bits_opt = self.proj.compile_options["use_region_bit_encoding"]
        if self.proj.rfi:
            if self.proj.compile_options["fastslow"]:
                if self.proj.compile_options["decompose"]:
                    self.spec['Topo'] = createIASysTopologyFragment(
                        adjData,
                        self.parser.proj.rfi.regions,
                        use_bits=use_bits_opt)
                    self.spec['EnvTopo'] = createIAEnvTopologyFragment(
                        adjData,
                        self.parser.proj.rfi.regions, actuatorList,
                        use_bits=use_bits_opt)
                    self.spec['SysImplyEnv'] = createIASysPropImpliesEnvPropLivenessFragment(
                        actuatorList,
                        self.parser.proj.rfi.regions,
                        sensorList, adjData,
                        use_bits=use_bits_opt)
                else:
                    self.spec['Topo'] = createIASysTopologyFragment(
                        adjData,
                        self.proj.rfi.regions,
                        use_bits=use_bits_opt)
                    self.spec['EnvTopo'] = createIAEnvTopologyFragment(
                        adjData,
                        self.proj.rfi.regions,
                        actuatorList,
                        use_bits=use_bits_opt)
                    self.spec['SysImplyEnv'] = createIASysPropImpliesEnvPropLivenessFragment(
                        actuatorList,
                        self.proj.rfi.regions,
                        sensorList,
                        adjData,
                        use_bits=use_bits_opt)
            else:
                if self.proj.compile_options["decompose"]:
                    self.spec['Topo'] = createTopologyFragment(
                        adjData,
                        self.parser.proj.rfi.regions,
                        use_bits=use_bits_opt)
                else:
                    self.spec['Topo'] = createTopologyFragment(
                        adjData,
                        self.proj.rfi.regions,
                        use_bits=use_bits_opt)
        else:
            self.spec['EnvTopo'] = createIAEnvTopologyFragment(
                [],
                [],
                actuatorList,
                use_bits=use_bits_opt)
            self.spec['SysImplyEnv'] = createIASysPropImpliesEnvPropLivenessFragment(
                actuatorList,
                [],
                sensorList,
                [],
                use_bits=use_bits_opt)
            self.spec['Topo'] = None

        # Environment prop of actuators
        if self.proj.compile_options["fastslow"]:
            self.spec['EnvTopo'] = '&\n '.join(filter(None, [createIAEnvActFragment(actuatorList), self.spec['EnvTopo']]))

        if self.proj.rfi:
            # Substitute any macros that the parsers passed us
            LTLspec_env = self.substituteMacros(
                LTLspec_env,
                self.proj.compile_options["fastslow"])
            LTLspec_sys = self.substituteMacros(
                LTLspec_sys,
                self.proj.compile_options["fastslow"])

            # If we are not using bit-encoding, we need to
            # explicitly encode a mutex for regions
            if not self.proj.compile_options["use_region_bit_encoding"]:
                # DNF version (extremely slow for core-finding)
                #mutex = "\n\t&\n\t []({})".format(" | ".join(["({})".format(" & ".join(["s."+r2.name if r is r2 else "!s."+r2.name for r2 in self.parser.proj.rfi.regions])) for r in self.parser.proj.rfi.regions]))

                if self.proj.compile_options["decompose"]:
                    region_list = self.parser.proj.rfi.regions
                else:
                    region_list = [region for region in self.proj.rfi.regions
                                   if not region.isObstacle and
                                   region.name != 'boundary']

                # Almost-CNF version
                exclusions = []
                for i, r1 in enumerate(region_list):
                    for r2 in region_list[i+1:]:
                        exclusions.append("!(s.{} & s.{})".format(r1.name, r2.name))
                mutex = "\n&\n\t []({})".format(" & ".join(exclusions))
                LTLspec_sys += mutex

            #self.spec.update(self.splitSpecIntoComponents(LTLspec_env, LTLspec_sys))

        # Set InitRegionSanityCheck
        if self.proj.rfi:
            # Add in a fragment to make sure that we start in a valid region
            if self.proj.compile_options["decompose"]:
                region_list = self.parser.proj.rfi.regions
            else:
                region_list = self.proj.rfi.regions
            self.spec['InitRegionSanityCheck'] = createInitialRegionFragment(region_list, use_bits=self.proj.compile_options["use_region_bit_encoding"])
            LTLspec_sys = '&\n '.join(filter(None, [LTLspec_sys, self.spec['InitRegionSanityCheck'], self.spec['Topo']]))
        else:
            self.spec['InitRegionSanityCheck'] = None

        if self.proj.compile_options['fastslow']:
            LTLspec_env = '&\n '.join(filter(None, [LTLspec_env, self.spec['EnvTopo'], self.spec['SysImplyEnv']]))

        if self.proj.rfi:
            ###### ENV Assumptions Learning #############
            ## Saving LTL Spec in separated parts to be used for assumption mining #####
            if self.proj.compile_options["use_region_bit_encoding"]:
                for key, value in spec.iteritems():
                    self.spec[key] = replaceRegionName(
                        value, bitEncode, regionList)

                if self.proj.compile_options['fastslow']:
                    for key, value in self.spec.iteritems():
                        self.spec[key] = replaceRegionName(
                            value, bitEncode, regionListCompleted)
            else:
                for key, value in spec.iteritems():
                    self.spec[key] = value

        # only write to LTLfile with specEditor
        if createLTL is True:
            createLTLfile(self.proj.getFilenamePrefix(),
                          LTLspec_env,
                          LTLspec_sys)
        #############################################

        if self.proj.compile_options["parser"] == "slurp":
            self.reversemapping = {self.postprocessLTL(line,sensorList,robotPropList).strip():line.strip() for line in oldspec_env + oldspec_sys}
            self.reversemapping[self.spec['Topo'].replace("\n","").replace("\t","").lstrip().rstrip("\n\t &")] = "TOPOLOGY"

        return self.spec, traceback, response
        #######################################

    def substituteMacros(self, text, fastslow):
        """
        Replace any macros passed to us by the parser.  In general, this is only necessary in cases
        where bitX propositions are needed, since the parser is not supposed to know about them.
        """

        # This creates a mirrored copy of topological constraints for the target we are following
        if "FOLLOW_SENSOR_CONSTRAINTS" in text:
            if not self.proj.compile_options["use_region_bit_encoding"]:
                ltlmop_logger.warning("Currently, bit encoding must be enabled for follow sensor")
            else:
                env_topology = self.spec['Topo'].replace("s.bit", "e.sbit")
                initreg_formula = createInitialRegionFragment(self.parser.proj.rfi.regions, use_bits=True).replace("s.bit", "e.sbit")

                sensorBits = ["sbit{}".format(i) for i in range(0,int(numpy.ceil(numpy.log2(len(self.parser.proj.rfi.regions)))))]
                for p in sensorBits:
                    if p not in self.proj.enabled_sensors:
                        self.proj.enabled_sensors.append(p)
                    if p not in self.proj.all_sensors:
                        self.proj.all_sensors.append(p)

                text = text.replace("FOLLOW_SENSOR_CONSTRAINTS", env_topology + "\n&\n" + initreg_formula)

        # Stay-there macros.  This can be done using just region names, but is much more concise
        # using bit encodings (and thus much faster to encode as CNF)

        if "STAY_THERE" in text:
            if self.proj.compile_options["decompose"]:
                text = text.replace("STAY_THERE", createStayFormula([r.name for r in self.parser.proj.rfi.regions], use_bits=self.proj.compile_options["use_region_bit_encoding"], fastslow=fastslow))
            else:
                text = text.replace("STAY_THERE", createStayFormula([r.name for r in self.proj.rfi.regions], use_bits=self.proj.compile_options["use_region_bit_encoding"], fastslow=fastslow))

        if "TARGET_IS_STATIONARY" in text:
            text = text.replace("TARGET_IS_STATIONARY", createStayFormula([r.name for r in self.parser.proj.rfi.regions], use_bits=self.proj.compile_options["use_region_bit_encoding"]).replace("s.","e.s"))

        return text

    def postprocessLTL(self, text, sensorList, robotPropList):
        """
        """
        # TODO: make everything use this
        if self.proj.compile_options["decompose"]:
            # substitute decomposed region names
            text = self._subDecompedRegion(text, '\\bs\.')
            text = self._subDecompedRegion(text, '\\be\.')

        # Get a list of region names
        regionList = self.getRegionList()

        # Define the number of bits needed to encode the regions
        numBits = int(math.ceil(math.log(len(regionList),2)))

        # creating the region bit encoding
        bitEncode = bitEncoding(len(regionList),numBits)
        currBitEnc = bitEncode['current']
        nextBitEnc = bitEncode['next']

        # switch to bit encodings for regions
        if self.proj.compile_options["use_region_bit_encoding"]:
            text = replaceRegionName(text, bitEncode, regionList)

        text = self.substituteMacros(text,self.proj.compile_options["fastslow"])

        return text

    def splitSpecIntoComponents(self, env, sys):
        spec = {}

        for agent, text in (("env", env), ("sys", sys)):
            for line in text.split("\n"):
                if line.strip() == '': continue

                if "[]<>" in line:
                    linetype = "goals"
                elif "[]" in line:
                    linetype = "trans"
                else:
                    linetype = "init"

                key = agent.title()+linetype.title()
                if key not in spec:
                    spec[key] = ""

                spec[key] += line + "\n"

        return spec

    def _checkForEmptyGaits(self):
        from simulator.ode.ckbot import CKBotLib

        # Initialize gait library
        self.library = CKBotLib.CKBotLib()

        err = 0
        libs = self.library
        libs.readLibe()
        # Check that each individual trait has a corresponding config-gait pair
        robotPropList = self.proj.enabled_actuators + self.proj.all_customs
        for act in robotPropList:
            act = act.strip("u's.")
            if act[0] == "T":
                act = act.strip("T_")
                #print act
                words = act.split("_and_")
                #print words
                config = libs.findGait(words)
                #print config
                if type(config) == type(None):
                    err_message = "No config-gait pair for actuator T_" + act + "\n"
                    ltlmop_logger.warning(err_message)
                    err = 1

    def _getSlugsCommand(self, execution=False, analysis=False):
        # Check that slugs is compiled
        self._setupSLUGS()

        slugs_path = os.path.join(
            self.proj.ltlmop_root,
            "etc", "slugs", "src", "slugs")

        # Construct Slugs Command
        cmd = [slugs_path, "--sysInitRoboticsSemantics"]

        # Set Slugs Options
        if analysis:
            cmd.append("--unrealizabilityAnalysis")
            ltlmop_logger.debug('Analyzing specification')
        else:
            if self.proj.compile_options["recovery"] and\
               (execution or not self.proj.compile_options['interactive']):
                cmd.extend(["--simpleRecovery", "--optimisticRecovery"])
                ltlmop_logger.debug('Synthesizing strategy with recovery')

            if (self.proj.compile_options["only_realizability"] or
               (self.proj.compile_options['interactive'] and not execution)):
                ltlmop_logger.debug('Only checking realizability')

            if not self.proj.compile_options["symbolic"] and\
               not self.proj.compile_options['interactive']:
                cmd.append("--explicitStrategy")
                ltlmop_logger.debug('Synthesizing explicit strategy')

            if self.proj.compile_options["symbolic"]:
                cmd.append("--symbolicStrategy")
                ltlmop_logger.debug('Synthesizing strategy with bdd')

            if self.proj.compile_options['interactive'] and execution:
                cmd.append("--interactiveStrategy")
                ltlmop_logger.debug('Using interacitve strategy mode')

            if self.proj.compile_options['neighbour_robot'] and\
               self.proj.compile_options["multi_robot_mode"] == "patching" or\
               self.proj.compile_options["winning_livenesses"]:
                cmd.append("--withWinningLiveness")
                ltlmop_logger.debug(
                    'Synthesizing strategy which also outputs livenesses')

        if self.proj.compile_options["cooperative_gr1"]:
            cmd.append("--cooperativeGR1Strategy")
            ltlmop_logger.debug(
                'Synthesizing strategy with cooperative strategy')

        # Pass *.slugins filename
        cmd.append(self.proj.getFilenamePrefix() + ".slugsin")

        # Add parameters required by the cost_spec
        cmd = self.proj.cost_spec.append_slugs_cmd(cmd)

        # Pass in Strategy File
        if not(self.proj.compile_options["only_realizability"] or
           self.proj.compile_options['interactive'] or analysis):
            # Get Strategy File Type
            if self.proj.compile_options['symbolic']:
                cmd.append(self.proj.getFilenamePrefix() + ".bdd")
            else:
                cmd.append(self.proj.getFilenamePrefix() + ".aut")

        return cmd

    def _getGROneCommand(self, module, refine=False):
        jtlv_path = os.path.join(self.proj.ltlmop_root, "etc", "jtlv")

        # Check that GROneMain, etc. is compiled
        if not os.path.exists(os.path.join(jtlv_path, "GROne", "GROneMain.class")):
            # TODO: automatically compile for the user
            raise RuntimeError("The Java synthesis code does not appear to be compiled yet.  Please run dist/setup.py before using LTLMoP.")

        # Windows uses a different delimiter for the java classpath
        delim = ";" if os.name == "nt" else ":"

        classpath = delim.join([os.path.join(jtlv_path, "jtlv-prompt1.4.0.jar"),
                                os.path.join(jtlv_path, "GROne")])

        cmd = ["java", "-ea", "-Xmx512m", "-cp", classpath, module, self.proj.getFilenamePrefix() + ".smv", self.proj.getFilenamePrefix() + ".ltl"]


        if refine:
            cmd += ["true"]

        return cmd

    def _autIsNonTrivial(self):
        """
        Check for a) empty automaton, or b) trivial initial-state automaton
         with no transitions
        (This can indicate unsatisfiable system initial conditions (case a),
         or an unsat environment (case b).)

        TODO: Do this in the Java code; it's super inefficient to
        load the whole aut just to check this.
        """
        enabled_sensors = self.proj.enabled_sensors
        if self.proj.rfi:
            if self.proj.compile_options["decompose"]:
                regions = self.parser.proj.rfi.regions
            else:
                regions = self.proj.rfi.regions

            if self.proj.compile_options["decompose"]:
                regions = self.parser.proj.rfi.regions
            else:
                regions = self.proj.rfi.regions

        if self.proj.compile_options["use_region_bit_encoding"]:
            sysRegions = copy.copy(regions)
            if self.proj.compile_options["recovery"]:
                # need to add dummy region as recovery allows extra system bits
                # Calculate the minimum number of bits necessary; note that we use max(1,...) because log(1)==0
                num_props = max(1, int(math.ceil(math.log(len(regions), 2))))
                for x in range(2**num_props-len(regions)):
                    sysRegions.append(None)

            region_domain = [strategy.Domain("region", sysRegions, strategy.Domain.B0_IS_MSB)]
        else:
            region_domain = [x.name for x in regions]
        enabled_sensors = self.proj.enabled_sensors

        if self.proj.compile_options['fastslow'] :
            if self.proj.compile_options["use_region_bit_encoding"]:
                envRegions = copy.copy(regions)
                if self.proj.compile_options["recovery"]:
                    # need to add dummy region as recovery allows extra environment bits
                    # Calculate the minimum number of bits necessary; note that we use max(1,...) because log(1)==0
                    num_props = max(1, int(math.ceil(math.log(len(regions), 2))))
                    for x in range(2**num_props-len(regions)):
                        envRegions.append(None)

                region_domain = [strategy.Domain("region", sysRegions, strategy.Domain.B0_IS_MSB)]
            else:
                region_domain = [x.name for x in regions]

            if self.proj.compile_options['fastslow'] :
                if self.proj.compile_options["use_region_bit_encoding"]:
                    envRegions = copy.copy(regions)
                    if self.proj.compile_options["recovery"]:
                        # need to add dummy region as recovery allows extra environment bits
                        # Calculate the minimum number of bits necessary; note that we use max(1,...) because log(1)==0
                        num_props = max(1, int(math.ceil(math.log(len(regions), 2))))
                        for x in range(2**num_props-len(regions)):
                            envRegions.append(None)

                    regionCompleted_domain = [strategy.Domain("regionCompleted", envRegions, strategy.Domain.B0_IS_MSB)]
                    enabled_sensors = [x for x in self.proj.enabled_sensors if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]

                else:
                    regionCompleted_domain = []
                    enabled_sensors = [x for x in enabled_sensors if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]
                    if self.proj.compile_options["decompose"]:
                        enabled_sensors.extend([r.name+"_rc" for r in self.parser.proj.rfi.regions])
                    else:
                        enabled_sensors.extend([r.name+"_rc" for r in self.proj.rfi.regions])
            else:
                regionCompleted_domain = []
                enabled_sensors = [x for x in enabled_sensors if not x.endswith('_rc') or x.startswith(tuple(self.proj.otherRobot))]
                if self.proj.compile_options["decompose"]:
                    enabled_sensors.extend([r.name+"_rc" for r in self.parser.proj.rfi.regions])
                else:
                    enabled_sensors.extend([r.name+"_rc" for r in self.proj.rfi.regions])
        else:
            regionCompleted_domain = []
            region_domain = []

        if self.proj.compile_options["symbolic"] or self.proj.compile_options['interactive'] or self.proj.compile_options['only_realizability']:
            ltlmop_logger.info("We will not check if the strategy is trivial or load the strategy with symbolic/interactive strategy or only realizability option.")
            return True

        strat = strategy.createStrategyFromFile(self.proj.getStrategyFilename(),
                                                self.proj.enabled_sensors,
                                                self.proj.enabled_actuators + self.proj.all_customs + self.proj.internal_props + [region_domain])

        nonTrivial = any([len(strat.findTransitionableStates({}, s)) > 0 for s in strat.iterateOverStates()])

        return nonTrivial

    ################## ENV Assumption Learning ##############
    def _analyze(self, generatedSpec = False):
    ##########################################################

        if self.proj.compile_options["synthesizer"].lower() == "jtlv":
            cmd = self._getGROneCommand("GROneDebug")
            ############## ENV ASSUMPTION LEARNING #################
            if generatedSpec:
                cmd[-1] = cmd[-1].replace(".ltl",'Generated.ltl')
            ########################################################

        elif self.proj.compile_options["synthesizer"].lower() == "slugs":
            cmd = self._getSlugsCommand(analysis=True)

        ltlmop_logger.debug(cmd)
        if cmd is None:
            return (False, False, [], "")

        subp = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=False)

        realizable = False
        unsat = False
        nonTrivial = False

        output = ""
        to_highlight = []
        for dline in subp.stdout:
            output += dline
            if "Specification is synthesizable!" in dline:
                realizable = True
                nonTrivial = self._autIsNonTrivial()
                if nonTrivial:
                    break

            ### Highlight sentences corresponding to identified errors ###

            # System unsatisfiability
            elif "System initial condition is unsatisfiable." in dline:
                to_highlight.append(("sys", "init"))
            elif "System transition relation is unsatisfiable." in dline:
                to_highlight.append(("sys", "trans"))
            elif "System highlighted goal(s) unsatisfiable" in dline:
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("sys", "goals", int(l)))
            elif "System highlighted goal(s) inconsistent with transition relation" in dline:
                to_highlight.append(("sys", "trans"))
                to_highlight.append(("sys", "init"))
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("sys", "goals", int(l)))
            elif "System initial condition inconsistent with transition relation" in dline:
                to_highlight.append(("sys", "init"))
                to_highlight.append(("sys", "trans"))

            # Environment unsatisfiability
            elif "Environment initial condition is unsatisfiable." in dline:
                to_highlight.append(("env", "init"))
            elif "Environment transition relation is unsatisfiable." in dline:
                to_highlight.append(("env", "trans"))
            elif "Environment highlighted goal(s) unsatisfiable" in dline:
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("env", "goals", int(l)))
            elif "Environment highlighted goal(s) inconsistent with transition relation" in dline:
                to_highlight.append(("env", "init"))
                to_highlight.append(("env", "trans"))
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("env", "goals", int(l)))
            elif "Environment initial condition inconsistent with transition relation" in dline:
                to_highlight.append(("env", "init"))
                to_highlight.append(("env", "trans"))


            # System unrealizability
            elif "System is unrealizable because the environment can force a safety violation" in dline:
                to_highlight.append(("sys", "trans"))
                to_highlight.append(("sys", "init"))
            elif "System highlighted goal(s) unrealizable" in dline:
                to_highlight.append(("sys", "trans"))
                to_highlight.append(("sys", "init"))
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("sys", "goals", int(l)))

            # Environment unrealizability
            elif "Environment is unrealizable because the system can force a safety violation" in dline:
                to_highlight.append(("env", "trans"))
            elif "Environment highlighted goal(s) unrealizable" in dline:
                to_highlight.append(("env", "trans"))
                for l in (dline.strip()).split()[-1:]:
                    to_highlight.append(("env", "goals", int(l)))

            if "unsatisfiable" in dline or "inconsistent" in dline :
                unsat = True

        subp.stdout.close()

        return (realizable, unsat, nonTrivial, to_highlight, output)

    def _coreFinding(self, to_highlight, unsat, badInit):
        #returns list of formulas that cause unsatisfiability/unrealizability (based on unsat flag).
        #takes as input sentences marked for highlighting, and formula describing bad initial states
        #from synthesis engine.

        #find number of states in automaton/counter for unsat/unreal core max unrolling depth ("recurrence diameter")
        proj_copy = deepcopy(self.proj)
        proj_copy.rfi = self.parser.proj.rfi
        proj_copy.sensor_handler = None
        proj_copy.actuator_handler = None
        proj_copy.h_instance = None

        if self.proj.rfi:
            proj_copy.rfi = self.parser.proj.rfi

            if self.proj.compile_options["decompose"]:
                regions = self.parser.proj.rfi.regions
            else:
                regions = self.proj.rfi.regions

            region_domain = strategy.Domain("region", regions, strategy.Domain.B0_IS_MSB)
            strat = strategy.createStrategyFromFile(self.proj.getStrategyFilename(),
                                                            self.proj.enabled_actuators + self.proj.all_customs + [region_domain], self.proj.enabled_sensors)
        else:
            strat = strategy.createStrategyFromFile(self.proj.getStrategyFilename(),
                                                            self.proj.enabled_actuators + self.proj.all_customs, self.proj.enabled_sensors)

        #find deadlocked states in the automaton (states with no out-transitions)
        deadStates = [s for s in strat.states if not strat.findTransitionableStates({}, from_state = s)]

        #find states that can be forced by the environment into the deadlocked set
        forceDeadStates = [(s, e) for s in strat.states for e in deadStates if e in strat.findTransitionableStates({}, from_state = s)]

        #LTL representation of these states and the deadlock-causing environment move in the next time step
        forceDeadlockLTL = map(lambda (s,e): " & ".join([s.getLTLRepresentation(swap_players=True), e.getLTLRepresentation(use_next=True, include_inputs=False, swap_players=True)]), forceDeadStates)

        #find livelocked goal and corresponding one-step propositional formula from spec (by stripping LTL operators)
        desiredGoal = [h_item[2] for h_item in to_highlight if h_item[1] == "goals"]


        if desiredGoal:
            desiredGoal = desiredGoal[0]


        def preventsDesiredGoal(s):
            #find states in the counterstrategy that prevent to desired goal (as indicated by the second component of the 'rank')
            rank_str = strat.findTransitionableStates({}, from_state = s)[0].goal_id #originally rank
            m = re.search(r"\(\d+,(-?\d+)\)", rank_str)
            if m is None:
                ltlmop_logger.error("Error parsing jx in automaton.  Are you sure the spec is unrealizable?")
                return
            jx = int(m.group(1))
            return (jx == desiredGoal)

        def sublistExists(list1, list2):
            #checks if list1 is a sublist of list2
            return ''.join(map(str, list2)) in ''.join(map(str, list1))

        desiredGoalSCCs = [(s,t) for s in strat.states for t in strat.findTransitionableStates({}, from_state = s) if preventsDesiredGoal(s) and preventsDesiredGoal(t)]

        counterTraces = True

        # IDENTIFY COUNTERTRACES
        for (s,t) in desiredGoalSCCs:
            if [(s2,t2) for (s2,t2) in desiredGoalSCCs if s2==s and t2!=t]:
                counterTraces = False


        if counterTraces:
            cycles = strat.findAllCycles()
            desiredGoalCycles = [c for c in cycles if all(map(preventsDesiredGoal, c))]
            #desiredGoalCycles = [c for c in desiredGoalCycles if not any(map(lambda x: sublistExists(x, c), [x for x in desiredGoalCycles if x!=c]))]
            #forceLivelockLTL = [[fro]+c[0:4] for c in desiredGoalCycles for fro in aut.states for to in c if (to in fro.transitions and fro not in c)]

        #else:
            #desiredGoalSCCs = [(s,t) for s in strat.states for t in strat.findTransitionableStates({}, from_state = s) if preventsDesiredGoal(s) and preventsDesiredGoal(t)]
            #print [s.getName()+t.getName() for (s,t) in desiredGoalSCCs]


        #size of counterstrategy and number of regions
        #useful for determininig a good unroll depth
        numStates = len(strat.states)
        if self.proj.rfi:
            numRegions = len(self.parser.proj.rfi.regions)

        if forceDeadlockLTL:
            deadlockFlag = True
            badStatesLTL = forceDeadlockLTL
        else:
            #this means livelock
            deadlockFlag = False
            badStatesLTL = badInit

        #################################
        #                               #
        # get conjuncts to be minimized #
        #                               #
        #################################

        if self.proj.rfi:
            #topology
            topo =self.spec['Topo'].replace('\n','')
            topo = topo.replace('\t','')
        else:
            topo = ''

        #have to use all initial conditions if no single bad initial state given
        useInitFlag = badInit is None

        #other highlighted LTL formulas
        conjuncts = self.ltlConjunctsFromBadLines(to_highlight, useInitFlag)

        #filter out props that are actually used
        #self.propList = [p for p in self.propList if [c for c in conjuncts if p in c] or [c for c in badStatesLTL if p in c and not unsat] or p in topo]

        cmd = self._getPicosatCommand()

        cyc_enc = True

        if unsat:
            guilty = self.unsatCores(cmd, topo,badInit,conjuncts,10,1)#returns LTL conjuncts
        else:
            if counterTraces:
                guilty = self.unrealCores(cmd, topo, badInit, badStatesLTL, conjuncts, deadlockFlag, desiredGoalCycles,counterTraces,cyc_enc)#returns LTL conjuncts
            else:
                return []
                #guilty = self.unrealCores(cmd, topo, badInit, badStatesLTL, conjuncts, deadlockFlag, desiredGoalSCCs)#returns LTL conjuncts

        return guilty

    def unsatCores(self, cmd, topo, badInit, conjuncts,maxDepth,initDepth):
        #returns list of guilty LTL formulas
        #takes LTL formulas for topo, badInit and conjuncts separately because they are used in various combinations later

        if not conjuncts and badInit == "":
            #this means that the topology is unsatisfiable by itself (not common since we auto-generate)
            return topo
        else:
            #try the different cases of unsatisfiability (need to pass in command and proplist to coreUtils function)
            self.trans, guilty = unsatCoreCases(cmd, self.propList, topo, badInit, conjuncts,maxDepth,initDepth)

        return guilty

    def unrealCores(self, cmd, topo, badInit, badStatesLTL, conjuncts, deadlockFlag, aux, counterTraces=False, cyc_enc=True):
        #returns list of guilty LTL formulas FOR THE UNREALIZABLE CASE
        #takes LTL formulas representing the topology and other highlighted conjuncts as in the unsat case.
        #also takes LTL representation of deadlocked/livelocked states ('badStatesLTL)
        #returns LTL formulas that appear in the guilty set for *any* deadlocked or livelocked state,
        #i.e. formulas that cause deadlock/livelock in these states

        #try the different cases of unsatisfiability (need to pass in command and proplist to coreUtils function)
        if deadlockFlag:
            initDepth = 1
            maxDepth = 10
        else:
            initDepth = 1
            #initDepth = max([len(c) for c in cycles])
            maxDepth = 10
            if counterTraces:
                allCycles = map(lambda (i,x): stateCycleToCNFs(i,x, self.propList, maxDepth, cyc_enc), enumerate(aux))
                if cyc_enc:
                    extra = [item for sublist1 in allCycles for sublist2 in sublist1 for item in sublist2]
                    extra = extra + [' '.join(["cycle"+str(i) for i in range(0,len(aux))]+["0\n"])]
                else:
                    extra = allCycles
            else:
                extra = unwindSCCs(aux, self.propList, maxDepth)


#        TODO: see if there is a way to call pool.map with processes that also use pools
#
#        sys.stdout = StringIO.StringIO()
#
#        pool = Pool()
#        guiltyList = pool.map(unsatCoreCasesWrapper, itertools.izip(itertools.repeat(cmd), itertools.repeat(self.propList), itertools.repeat(topo), badStatesLTL, itertools.repeat(conjuncts), itertools.repeat(initDepth), itertools.repeat(maxDepth)))
#        pool.terminate()
#
#        sys.stdout = sys.__stdout__

        if deadlockFlag:
            guiltyList = map(lambda d: unsatCoreCases(cmd, self.propList, topo, d, conjuncts, maxDepth, initDepth), badStatesLTL)
        else:
            if counterTraces:
                if cyc_enc:
                    guiltyList = [unsatCoreCases(cmd, self.propList, topo, '', conjuncts, maxDepth, initDepth, extra)]
                else:
                    guiltyList = map(lambda c: unsatCoreCases(cmd, self.propList, topo, c[1], conjuncts, maxDepth, c[2], c[0], cyc_enc), zip(extra, [cyc[0].getLTLRepresentation(swap_players=True) for cyc in aux], [len(c) for c in aux]))

            else:
                #guiltyList = map(lambda c: unsatCoreCases(cmd, self.propList, topo, '', conjuncts, maxDepth, initDepth, extra))
                guiltyList = [unsatCoreCases(cmd, self.propList, topo, '', conjuncts, maxDepth, initDepth, extra)]

        guilty = reduce(set.union,map(set,[g for t, g in guiltyList]))

        return guilty

    def _getPicosatCommand(self):
        # look for picosat

        paths = [p for p in glob.glob(os.path.join(self.proj.ltlmop_root,"lib","cores","picosat-*")) if os.path.isdir(p)]
        if len(paths) == 0:
            ltlmop_logger.error("Where is your sat solver? We use Picosat.")
            # TODO: automatically compile for the user
            return None
        else:
            ltlmop_logger.debug("Found Picosat in " + paths[0])

        if os.name == "nt":
            cmd = os.path.join(paths[0],"picomus.exe")
        else:
            cmd = [os.path.join(paths[0],"picomus")]

        return cmd

    def ltlConjunctsFromBadLines(self, to_highlight, useInitFlag):
        #given the lines to be highlighted by the initial analysis in _analyze(),
        #returns a list of LTL formulas that, when conjuncted, cause unsatisfiability

        conjuncts = []

        for h_item in to_highlight:
            tb_key = h_item[0].title() + h_item[1].title()

            newCs = []
            if h_item[1] == "goals":
                #special treatment for goals: (1) we already know which one to highlight, and (2) we need to check both tenses
                #TODO: separate out the check for present and future tense -- what if you have to toggle but can still do so infinitely often?
                #newCs = ivd[self.traceback[tb_key][h_item[2]]].split('\n')
                goals = self.spec[tb_key].split('\n')
                newCs = [goals[h_item[2]]]
                newCsOld = newCs

            elif h_item[1] == "trans" or h_item[1] == "init" and useInitFlag:
                if not h_item[1] == "trans" or self.proj.rfi:
                    newCs =  self.spec[tb_key].replace("\t", "\n").split("\n")

            conjuncts.extend(newCs)

        return conjuncts

    def _synthesize(self, with_safety_aut=False):
        """ Call the synthesis tool, and block until it completes.
        Returns success flags `realizable` and `realizableFS`, and the raw
        synthesizer log output. """
        cmd = self._getGROneCommand("GROneMain")
        if cmd is None:
            return (False, False, "")

        log_string = StringIO.StringIO()

        tic = globalConfig.best_timer()

        self._synthesizeAsync(log_function=log_string.write)

        self.synthesis_complete.wait()  # Block here until synthesis is done
        toc = globalConfig.best_timer()
        ltlmop_logger.info(
            "Synthesized Strategy in {} seconds.".format(toc - tic))

        return (self.realizable, self.realizableFS, log_string.getvalue())

    def prepareSlugsInput(self):
        """ Convert from JTLV input format (.smv+.ltl) to Slugs input format (.slugsin)
            using the script provided by Slugs.

            This is a stop-gap fix; eventually we should just produce the input
            directly instead of using the conversion script. """

        # Import Converter function
        from translateFromLTLMopLTLFormatToSlugsFormat import performConversion

        # Call the conversion script
        with open(self.proj.getFilenamePrefix() + ".slugsin", "w") as f:
            sys.stdout = f
            performConversion(self.proj.getFilenamePrefix() + ".smv",
                              self.proj.getFilenamePrefix() + ".ltl")
            sys.stdout = sys.__stdout__

    def _synthesizeAsync(self, log_function=None,
                         completion_callback_function=None):
        """ Asynchronously call the synthesis tool.
            This function will return immediately after spawning a subprocess.

            `log_function` will be called with a string argument every time the
                subprocess generates a line of text.
            `completion_callback_function` will be called when synthesis
                finishes, with two arguments: the success flags `realizable`
                and `realizableFS`.
        """

        if self.proj.compile_options["synthesizer"].lower() == "jtlv":
            # Find the synthesis tool
            cmd = self._getGROneCommand("GROneMain")

            # Add any extra compiler options
            if self.proj.compile_options["fastslow"]:
                cmd.append("--fastslow")
            if self.proj.compile_options["symbolic"]:
                cmd.append("--symbolic")

            REALIZABLE_MESSAGE = "Specification is synthesizable!"
            REALIZABLE_FS_MESSAGE = "Specification is synthesizable under fast/slow!"

        elif self.proj.compile_options["synthesizer"].lower() == "slugs":
            # Find the synthesis tool
            cmd = self._getSlugsCommand()

            # Create proper input for Slugs
            ltlmop_logger.info("Preparing Slugs input...")
            self.prepareSlugsInput()

            REALIZABLE_MESSAGE = "RESULT: Specification is realizable"
            REALIZABLE_FS_MESSAGE = "RESULT: Specification is realizable"
        else:
            raise RuntimeError("Invalid synthesizer: {!r}".format(self.proj.compile_options["synthesizer"]))

        self.realizable = False
        self.realizableFS = False

        # Define some wrappers around the callback functions so we can parse the output
        # of the synthesis tool and return it in a meaningful way.
        def onLog(text):
            """ Intercept log callbacks to check for realizability status. """

            if REALIZABLE_MESSAGE in text:
                self.realizable = True
            if REALIZABLE_FS_MESSAGE is not None and REALIZABLE_FS_MESSAGE in text:
                self.realizableFS = True

            # You'll pass this on, won't you
            if log_function is not None:
                log_function(text)

        # Create a flag for convenience
        self.synthesis_complete = threading.Event()

        def onSubprocessComplete():
            if completion_callback_function is not None:
                completion_callback_function(self.realizable,
                                             self.realizableFS)
            self.synthesis_complete.set()
            self.synthesis_subprocess = None

        # Kick off the subprocess
        ltlmop_logger.info("Synthesizing a strategy...")

        self.synthesis_subprocess = AsynchronousProcessThread(
            cmd, onSubprocessComplete, onLog)

    def abortSynthesis(self):
        """ Kill any running synthesis process. """

        if self.synthesis_subprocess is not None:
            ltlmop_logger.warning("Aborting synthesis!")
            self.synthesis_subprocess.kill()
            self.synthesis_complete = None
            self.synthesis_subprocess = None

    def compile(self):
        if self.proj.compile_options["decompose"]:
            ltlmop_logger.info("Decomposing...")
            self._decompose()
        ltlmop_logger.info("Writing LTL file...")
        spec, tb, resp = self._writeLTLFile()
        ltlmop_logger.info("Writing SMV file...")
        self._writeSMVFile()

        if tb is None:
            ltlmop_logger.error("Compilation aborted")
            return

        #self._checkForEmptyGaits()
        ltlmop_logger.info("Synthesizing a strategy...")

        return self._synthesize()

    def _iterateCores(self):
        if self.proj.compile_options["synthesizer"].lower() != "jtlv":
            raise RuntimeError("Analysis is currently only supported when using JTLV.")

        cmd = self._getGROneCommand("GROneDebug", True)
        if cmd is None:
            return (False, False, [], "")

        subp = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=False)

        to_highlight = []
        output = ""
        for dline in subp.stdout:
            output += dline
            if "Guilty safety conjuncts" in dline:
                guilty = re.findall(r'([0-9]+)\s*', dline)
                for g in guilty:
                    to_highlight.append(("sys", "trans", int(g)))

        subp.stdout.close()
        print "OUTPUT", output
        return to_highlight

    def getRegionList(self):
        """ Returns the correct list of region names

            Uses regions from parser.proj or self.proj depending
            on the "decompose" compile option
        """

        if self.proj.compile_options["decompose"]:
            regionList = self.parser.proj.rfi.regionList()
        else:
            regionList = self.proj.rfi.regionList()

        return regionList

    def _subDecompedRegion(self, fragment, prefix=""):
        """ Replaces the names of regions with their decomposed versions

            :param fragment: The Ltl fragment conatining region names to
                             be replaced
            :param prefix: Prepend name with prefix string when searching
            :return: The ltl fragement with all of the regions replace with
                     their decomposed versions
        """

        # substitute decomposed region names
        for r in self.proj.rfi.regions:
            # Only update region name if not an obstacle or the boundary region
            if not (r.isObstacle or r.isBoundary()):
                fragment = re.sub(prefix + r.name + '\\b',
                                  self.parser.proj.mappedRegion(r.name, "s."),
                                  fragment)

        return fragment
