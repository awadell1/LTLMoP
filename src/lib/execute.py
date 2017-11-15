#!/usr/bin/env python

""" =================================================
    execute.py - Top-level hybrid controller executor
    =================================================

    This module executes a hybrid controller for a robot in a simulated or real environment.

    :Usage: ``execute.py [-hn] [-p listen_port] [-a automaton_file] [-s spec_file]``

    * The controlling automaton is imported from the specified ``automaton_file``.

    * The supporting handler modules (e.g. sensor, actuator, motion control, simulation environment initialization, etc)
      are loaded according to the settings in the config file specified as current in the ``spec_file``.

    * If no port to listen on is specified, an open one will be chosen randomly.
    * Unless otherwise specified with the ``-n`` or ``--no_gui`` option, a status/control window
      will also be opened for informational purposes.
"""

import sys, os, getopt, textwrap
import threading, subprocess, time


# Climb the tree to find out where we are
p = os.path.abspath(__file__)
t = ""
while t != "src":
    (p, t) = os.path.split(p)
    if p == "":
        print "I have no idea where I am; this is ridiculous"
        sys.exit(1)

sys.path.append(os.path.join(p,"src","lib"))

import fsa, project
import handlerSubsystem
import strategy
from copy import deepcopy
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
import xmlrpclib
import socket
import random
import math
import traceback
from resynthesis import ExecutorResynthesisExtensions
from executeStrategy import ExecutorStrategyExtensions
import globalConfig, logging

###### ENV VIOLATION CHECK ######
import copy
import specCompiler

import LTLParser.LTLcheck
import logging
import LTLParser.LTLFormula 
#################################

# -----------------------------------------#
# -------- two_robot_negotiation ----------#
# -----------------------------------------#
import negotiationMonitor.robotClient
# -----------------------------------------#

####################
# HELPER FUNCTIONS #
####################

def usage(script_name):
    """ Print command-line usage information. """

    print textwrap.dedent("""\
                              Usage: %s [-hn] [-p listen_port] [-a automaton_file] [-s spec_file]

                              -h, --help:
                                  Display this message
                              -n, --no-gui:
                                  Do not show status/control window
                              -p PORT, --xmlrpc-listen-port PORT:
                                  Listen on PORT for XML-RPC calls
                              -a FILE, --aut-file FILE:
                                  Load automaton from FILE
                              -s FILE, --spec-file FILE:
                                  Load experiment configuration from FILE """ % script_name)

class LTLMoPExecutor(ExecutorStrategyExtensions,ExecutorResynthesisExtensions, object):
    """
    This is the main execution object, which combines the synthesized discrete automaton
    with a set of handlers (as specified in a .config file) to create and run a hybrid controller
    """

    def __init__(self):
        """
        Create a new execution context object
        """
        super(LTLMoPExecutor, self).__init__()

        self.proj = project.Project() # this is the project that we are currently using to execute
        self.strategy = None

        # Choose a timer func with maximum accuracy for given platform
        if sys.platform in ['win32', 'cygwin']:
            self.timer_func = time.clock
        else:
            self.timer_func = time.time

        self.externalEventTarget = None
        self.externalEventTargetRegistered = threading.Event()
        self.postEventLock = threading.Lock()
        self.runStrategy = threading.Event()  # Start out paused
        self.alive = threading.Event()
        self.alive.set()

        self.current_outputs = {}     # keep track on current outputs values (for actuations)
        ########## ENV Assumption Learning ######
        self.compiler = None                   
        self.LTLViolationCheck = None
        self.analysisDialog = None
        self.to_highlight = None
        self.tracebackTree = None               # tells you init, trans and sys line no 
        self.path_LTLfile = None                    # path of the .ltl file
        self.LTL2SpecLineNumber = None          # mapping from LTL to structed english
        self.userAddedEnvLivenessEnglish = []          # keep track of liveness added by the user in English
        self.userAddedEnvLivenessLTL = []          # keep track of liveness added by the user in LTL
        self.originalLTLSpec      = {}          # save the original Spec for exporting
        self.currentViolationLineNo = []
        self.LTLSpec  = {}
        self.sensor_strategy = None
        
        ############# NEW THING FOR THRESHOLDING FOR RESYNTHESIS
        self.envViolationCount = 0    
        self.envViolationThres = 5
        
        ################# WHAT MODE ARE WE IN
        self.recovery = False
        self.ENVcharacterization = True
        #########################################
        
        # -----------------------------------------#
        # -------- two_robot_negotiation ----------#
        # -----------------------------------------#
        self.robClient = None
        self.old_violated_specStr = []
        self.prev_z  = 0
        # -----------------------------------------#
        

    def postEvent(self, eventType, eventData=None):
        """ Send a notice that an event occurred, if anyone wants it """

        with self.postEventLock:
            if self.externalEventTarget is None:
                return

            try:
                self.externalEventTarget.handleEvent(eventType, eventData)
            except socket.error as e:
                logging.warning("Could not send event to remote event target: %s", e)
                logging.warning("Forcefully unsubscribing target.")
                self.externalEventTarget = None

    def loadSpecFile(self, filename):
        # Update with this new project
        self.proj = project.Project()
        self.proj.loadProject(filename)
        self.hsub = handlerSubsystem.HandlerSubsystem(self, self.proj.project_root)


        # Tell GUI to load the spec file
        self.postEvent("SPEC", self.proj.getFilenamePrefix() + ".spec")

    def loadAutFile(self, filename):
        """
        This function loads the the .aut/.bdd file named filename and returns the strategy object.
        filename (string): name of the file with path included
        """
        #logging.debug([x.name.encode('ascii') for x in self.proj.rfi.regions])
        region_domain = strategy.Domain("region",  self.proj.rfi.regions, strategy.Domain.B0_IS_MSB)
        strat = strategy.createStrategyFromFile(filename,
                                                self.proj.enabled_sensors,
                                                self.proj.enabled_actuators + self.proj.all_customs +  self.proj.internal_props + [region_domain])

        return strat

    def _getCurrentRegionFromPose(self, rfi=None):
        # TODO: move this to regions.py
        if rfi is None:
            rfi = self.proj.rfi

        pose = self.hsub.coordmap_lab2map(self.hsub.getPose())

        region = next((i for i, r in enumerate(rfi.regions) if r.name.lower() != "boundary" and \
                        r.objectContainsPoint(*pose)), None)

        if region is None:
            logging.warning("Pose of {} not inside any region!".format(pose))

        return region

    def shutdown(self):
        self.runStrategy.clear()
        logging.info("QUITTING.")

        all_handler_types = ['init', 'pose', 'locomotionCommand', 'drive', 'motionControl', 'sensor', 'actuator']

        for htype in all_handler_types:
            logging.info("Terminating {} handler...".format(htype))
            if htype in self.proj.h_instance:
                if isinstance(self.proj.h_instance[htype], dict):
                    handlers = [v for k,v in self.proj.h_instance[htype].iteritems()]
                else:
                    handlers = [self.proj.h_instance[htype]]

                for h in handlers:
                    if hasattr(h, "_stop"):
                        logging.debug("Calling _stop() on {}".format(h.__class__.__name__))
                        h._stop()
                    else:
                        logging.debug("{} does not have _stop() function".format(h.__class__.__name__))
            else:
                logging.debug("{} handler not found in h_instance".format(htype))
                
        # ----------------------------- #
        # -- two_robot_negotiation  --- #
        # ----------------------------- #
        self.robClient.closeConnection()
        # ----------------------------- #
        
        self.alive.clear()

    def pause(self):
        """ pause execution of the automaton """
        self.runStrategy.clear()
        time.sleep(0.1) # Wait for FSA to stop
        self.postEvent("PAUSE")

    def resume(self):
        """ start/resume execution of the automaton """
        self.runStrategy.set()

    def isRunning(self):
        """ return whether the automaton is currently executing """
        return self.runStrategy.isSet()

    def registerExternalEventTarget(self, address):
        self.externalEventTarget = xmlrpclib.ServerProxy(address, allow_none=True)

        # Redirect all output to the log
        redir = RedirectText(self.externalEventTarget.handleEvent)

        sys.stdout = redir
        sys.stderr = redir

        self.externalEventTargetRegistered.set()

    def initialize(self, spec_file, strategy_file, firstRun=True):
        """
        Prepare for execution, by loading and initializing all the relevant files (specification, map, handlers, strategy)
        If `firstRun` is true, all handlers will be imported; otherwise, only the motion control handler will be reloaded.
        """

        # load project only first time; otherwise self.proj is modified in-place
        # TODO: make this less hacky
        if firstRun:
            self.loadSpecFile(spec_file)

            if self.proj.compile_options['decompose']:
                self.proj.rfiold = self.proj.rfi  # Save the undecomposed regions

        if self.proj.compile_options['decompose']:
            self.proj.rfi = self.proj.loadRegionFile(decomposed=True)

        if self.proj.current_config == "":
            logging.error("Can not simulate without a simulation configuration.")
            logging.error("Please create one by going to [Run] > [Configure Simulation...] in SpecEditor and then try again.")
            sys.exit(2)

        logging.info("Setting current executing config...")
        self.hsub.setExecutingConfig(self.proj.current_config)

        # make sure the coord transformation function is ready
        # get the main robot config
        robot_config = self.hsub.executing_config.getRobotByName(self.hsub.executing_config.main_robot)
        self.hsub.coordmap_map2lab, self.hsub.coordmap_lab2map = robot_config.getCoordMaps()
        self.proj.coordmap_map2lab, self.proj.coordmap_lab2map = robot_config.getCoordMaps()


        # Import the relevant handlers
        if firstRun:
            # Instantiate all handlers
            logging.info("Instantiate all handlers...")
            self.hsub.instantiateAllHandlers()

            logging.info("Preparing proposition mapping...")
            self.hsub.prepareMapping()
        else:
            #print "Reloading motion control handler..."
            #self.proj.importHandlers(['motionControl'])
            pass

        # We are done initializing at this point if there is no aut file yet
        if strategy_file is None:
            return

        # TODO: maybe an option for BDD here later
        # Load automaton file
        new_strategy = self.loadAutFile(strategy_file)

        if firstRun:
            ### Wait for the initial start command
            logging.info("Ready.  Press [Start] to begin...")
            self.runStrategy.wait()

        # -----------------------------------------#
        # -------- two_robot_negotiation ----------#
        self.robClient = negotiationMonitor.robotClient.RobotClient(self.hsub,self.proj)
        self.robClient.updateRobotRegion(self.proj.rfi.regions[self._getCurrentRegionFromPose()])
        self.negotiationStatus = self.robClient.checkNegotiationStatus()
        # -----------------------------------------#        
        
        ### Figure out where we should start from by passing proposition assignments to strategy and search for initial state
        ### pass in sensor values, current actuator and custom proposition values, and current region object

        ## Region
        # FIXME: make getcurrentregion return object instead of number, also fix the isNone check
        init_region = self.proj.rfi.regions[self._getCurrentRegionFromPose()]
        if init_region is None:
            logging.error("Initial pose not inside any region!")
            sys.exit(-1)

        logging.info("Starting from initial region: " + init_region.name)
        init_prop_assignments = {"region": init_region}

        # initialize all sensor and actuator methods
        logging.info("Initializing sensor and actuator methods...")
        self.hsub.initializeAllMethods()

        ## outputs
        if firstRun or self.strategy is None:
            # save the initial values of the actuators and the custom propositions
            for prop in self.proj.enabled_actuators + self.proj.all_customs + self.proj.internal_props:
                self.current_outputs[prop] = (prop in self.hsub.executing_config.initial_truths)

        init_prop_assignments.update(self.current_outputs)

        ## inputs
        # ---- two_robot_negotiation ----- # 
        # Wait until the other robot is ready
        # Make sure the other robot is loaded
        logging.info('Waiting for other robots to be ready')
        otherRobotsReady = False
        while not otherRobotsReady:
            for key, value in self.hsub.getSensorValue(self.proj.enabled_sensors).iteritems():
                if value is None:
                    break
            else:
                otherRobotsReady = True
        # -------------------------------- #
        init_prop_assignments.update(self.hsub.getSensorValue(self.proj.enabled_sensors))
        
        #search for initial state in the strategy
        if firstRun:
            init_state = new_strategy.searchForOneState(init_prop_assignments)
        else:
            init_state = new_strategy.searchForOneState(init_prop_assignments, goal_id = self.prev_z)
        
        ######## ENV Assumption Learning ###########                  
        if firstRun:
            
            # synthesize our controller again just to see if it's realizable and replace spec if FALSE
            self.compiler = specCompiler.SpecCompiler(spec_file)
            self.compiler._decompose()  # WHAT DOES IT DO? DECOMPOSE REGIONS?
            ########### 
            #self.tracebackTree : separate spec lines to spec groups
            #############
            self.spec, self.tracebackTree, response = self.compiler._writeLTLFile()#False)
            self.originalLTLSpec  = self.spec.copy()
            realizable, realizableFS, output  = self.compiler._synthesize()
            
            # initializing dialog in simGUI when violation occurs
            self.simGUILearningDialog = ["Added current inputs", "Added current and incoming inputs", "Added current, incoming inputs and current outputs"] 
            
            # for mapping from lineNo to LTL
            for key,value in self.compiler.LTL2SpecLineNumber.iteritems():
                self.LTLSpec[ value ] = key.replace("\t","").replace("\n","").replace(" ","")

            self.originalSpec = copy.deepcopy(self.spec)
            if not realizable:
                # start with always false
                self.oriEnvTrans = '[](FALSE)&' #added but should never be used for the unrealizable case.
                self.spec['EnvTrans'] = "\t[](FALSE) &\n"
                self.EnvTransRemoved = self.tracebackTree["EnvTrans"] 
            else:
                # put all clauses in EnvTrans into conjuncts           
                #self.oriEnvTrans = self.spec['EnvTrans'].replace("\t","").replace("\n","").replace(" ","")[:-1]
                #self.spec['EnvTrans'] = '[](('+self.spec['EnvTrans'].replace("\t","").replace("\n","").replace(" ","").replace('[]','')[:-1] +'))&\n'
                self.oriEnvTrans = self.spec['EnvTrans'][:-2]
                self.spec['EnvTrans'] = '[](('+self.spec['EnvTrans'].replace(" ","").replace('[]','')[:-2] +'))&\n'
                self.EnvTransRemoved = []
             
            # rewrite ltl file   
            self.recreateLTLfile(self.proj)
            
            # path of ltl file to be passed to the function 
            self.path_LTLfile =  os.path.join(self.proj.project_root,self.proj.getFilenamePrefix()+".ltl")  
            #create LTL checking object
            self.LTLViolationCheck = LTLParser.LTLcheck.LTL_Check(self.path_LTLfile,self.compiler.LTL2SpecLineNumber,self.spec)
            
            #safe a copy of the original sys initial condition (for resynthesis later)
            self.originalSysInit = self.spec['SysInit']
            
            # pass in current env assumptions if we have some
            if realizable:
                self.LTLViolationCheck.ltl_treeEnvTrans = LTLParser.LTLFormula.parseLTL(str(self.oriEnvTrans))       
                self.LTLViolationCheck.env_safety_assumptions_stage = {"1": self.spec['EnvTrans'][:-3] , "3": self.spec['EnvTrans'][:-3] , "2": self.spec['EnvTrans'][:-3] }

            else:
                self.LTLViolationCheck.ltl_treeEnvTrans = None
        
        #for using get LTLRepresentation of current sensors
        self.sensor_strategy = new_strategy.states.addNewState() 
        
        # resynthesize if cannot find initial state
        if init_state is None: 
            logging.debug('Finding init state failed.')
            for prop_name, value in self.hsub.getSensorValue(self.proj.enabled_sensors).iteritems():
                self.sensor_strategy.setPropValue(prop_name, value)
            self.postEvent('INFO','Finding init state failed.')
            init_state, new_strategy  = self.addStatetoEnvSafety(self.sensor_strategy, firstRun)            
        #############################################
        if init_state is None:
            logging.error("No suitable initial state found; unable to execute. Quitting...")
            sys.exit(-1)
        else:
            logging.info("Starting from state %s." % init_state.state_id)
            if self.strategy is None or init_state.state_id != self.strategy.current_state.state_id:
                self.postEvent('INFO', "Starting from state %s." % init_state.state_id)
        
        self.strategy = new_strategy
        self.strategy.current_state = init_state
        
        return  init_state, self.strategy

    def run(self):
        ### Get everything moving
        # Rate limiting is approximately 20Hz
        avg_freq = 20
        last_gui_update_time = 0

        # FIXME: don't crash if no spec file is loaded initially
        while self.alive.isSet():
            # Idle if we're not running
            if not self.runStrategy.isSet():
                self.hsub.setVelocity(0,0)

				###### ENV VIOLATION CHECK ######
                # pop up the analysis dialog                
                self.onMenuAnalyze(enableResynthesis = False, exportSpecification = True)               
                ################################
                    
                # wait for either the FSA to unpause or for termination
                while (not self.runStrategy.wait(0.1)) and self.alive.isSet():
                    pass

            # Exit immediately if we're quitting
            if not self.alive.isSet():
                break

            self.prev_outputs = self.strategy.current_state.getOutputs()
            self.prev_z = self.strategy.current_state.goal_id

            tic = self.timer_func()
            ###### ENV VIOLATION CHECK ######  
            last_next_states = self.last_next_states
            self.runStrategyIteration()
            current_next_states = self.last_next_states

            # Take a snapshot of our current sensor readings
            sensor_state = self.hsub.getSensorValue(self.proj.enabled_sensors) 
            for prop_name, value in sensor_state.iteritems():
                self.sensor_strategy.setPropValue(prop_name, value)

            # Check for environment violation - change the env_assumption_hold to int again 
            env_assumption_hold = self.LTLViolationCheck.checkViolation(self.strategy.current_state, self.sensor_strategy)
            
            # ---------- two_robot_negotiation ------------- # 
            # resynthesis request from the other robot
            self.negotiationStatus = self.robClient.checkNegotiationStatus()
            if (not self.exchangedSpec or not self.receivedSpec) and self.negotiationStatus == self.robClient.robotName:
                self.postEvent('NEGO','-- NEGOTIATION STARTED --')

                # synthesize a new controller to incorporate the actions of the other robot. 
                ###### ONE STEP ######
                realizable, oldSpecSysTrans_2, oldSpecEnvGoals_2 = self.synthesizeWithExchangedSpec(False)
                self.postEvent("NEGO",'Adding system guarantees with environment goals.')
                    
                if realizable:
                    self.robClient.setNegotiationStatus(True)
                    self.otherRobotStatus = False
                    self.postEvent('NEGO','Using exchanged specification.')
                    self.postEvent('RESOLVED','')

                    # reset violtion timestamp
                    self.violationTimeStamp = 0
                    self.robClient.setViolationTimeStamp(self.violationTimeStamp)
                    time.sleep(1)

                    self.exchangedSpec = True
                    # reinitialize automaton
                    spec_file = self.proj.getFilenamePrefix() + ".spec"
                    aut_file = self.proj.getFilenamePrefix() + ".aut"    
                    self.initialize(spec_file, aut_file, firstRun=False)  
                    continue
                    
                elif not self.sentSpec:
                    self.postEvent('NEGO','Unrealizable with exchanged info. Asking the other robot to incorporate our actions instead.')
                    
                    # send our spec to the other robot
                    self.robClient.sendSpec('SysGoals',self.spec['SysGoals']) 
                    self.robClient.sendSpec('EnvTrans',self.spec['EnvTrans'])
                    self.robClient.sendSpec('EnvGoals',self.spec['EnvGoals']) 
                    self.sentSpec = True
                    self.robClient.setNegotiationStatus("'" + self.proj.otherRobot[0] + "'")
                    
                    # wait until the other robot resynthesize its controller
                    while self.robClient.checkNegotiationStatus() != (True or False): 
                        time.sleep(2)
                        
                    if self.robClient.checkNegotiationStatus() == True:
                        #convert to the original specification
                        self._setSpecificationInitialConditionsToCurrentInDNF(self.proj,False, self.sensor_strategy)
                        # remove spec from other robots and resynthesize
                        self.spec = copy.deepcopy(self.originalSpec)
                        self.recreateLTLfile(self.proj, spec = self.originalSpec)
                        realizable, realizableFS, output  = self.compiler._synthesize()

                        self.otherRobotStatus = True # env characterization disabled
                        self.postEvent('NEGO','The other robot has incorporated our action. Using original specification.')
                        self.postEvent('NEGO','-- NEGOTIATION ENDED --')
                        self.postEvent('RESOLVED','')

                        # reset violtion timestamp
                        self.violationTimeStamp = 0
                        self.robClient.setViolationTimeStamp(self.violationTimeStamp)
                        time.sleep(1)

                    else:
                        #TODO: spec analysis needed.
                        self.postEvent('NEGO','Negotiation Failed. Spec Analysis is needed.')
                        self.postEvent('NEGO','-- NEGOTIATION ENDED --')
                        self.onMenuAnalyze(enableResynthesis = False, exportSpecification = True)      
                        return
                else: # sent spec before
                    #TODO: spec analysis needed.
                    self.postEvent('NEGO','Negotiation Failed. Spec Analysis is needed.')
                    self.postEvent('NEGO','-- NEGOTIATION ENDED --')
                    self.onMenuAnalyze(enableResynthesis = False, exportSpecification = True)
                    return

                self.exchangedSpec = True

            """    
            # if the other robot is requesting spec from us
            self.robClient.checkRequestSpec()
            for specType in self.robClient.specRequestFromOther:
                # send SysGoals, EnvTrans and EnvGoals
                self.robClient.sendSpec(specType,self.spec[specType]) 

            self.robClient.specRequestFromOther = []
            """
            # ------------------------------------------- #
            
            # assumption didn't hold
            if not env_assumption_hold:
            
                # ------------ two_robot_negotiation ----------#
                self.violationTimeStamp = time.clock()
                # store time stamp of violation            
                if not self.otherRobotStatus:
                    self.robClient.setViolationTimeStamp(self.violationTimeStamp)
                # ---------------------------------------------# 
                
                # count the number of next state changes
                if last_next_states != current_next_states:
                    self.envViolationCount += 1
                
                #self.postEvent("VIOLATION", "self.LTLViolationCheck.violated_spec_line_no:" + str(self.LTLViolationCheck.violated_spec_line_no))    
                #self.postEvent("VIOLATION", "self.currentViolationLineNo:" + str(self.currentViolationLineNo)) 
                # print out the violated specs
                for x in self.LTLViolationCheck.violated_spec_line_no:
                    if x not in self.currentViolationLineNo:
                        if x == 0 :
                            if len(self.LTLViolationCheck.violated_spec_line_no) == 1 and len(self.currentViolationLineNo) == 0:
                                self.postEvent("VIOLATION","Detected violation of env safety from env characterization")
                        else:                 
                            self.postEvent("VIOLATION","Detected the following env safety violation:" )
                            self.postEvent("VIOLATION", str(self.proj.specText.split('\n')[x-1]))
                
                for x in self.LTLViolationCheck.violated_specStr:
                    if x not in self.old_violated_specStr:
                        self.postEvent("VIOLATION", x)
                
                # save a copy     
                self.old_violated_specStr = self.LTLViolationCheck.violated_specStr
                
                if self.ENVcharacterization:    
                    if self.recovery:
                        ########################################
                        #### FOR BOTH LEANRING AND RECOVERY  ###
                        ########################################
                        if str(self.strategy.current_state.state_id) in [x.state_id for x in self.last_next_states] \
                        or self.envViolationCount == self.envViolationThres:
                            
                            # reset next state difference count
                            self.envViolationCount = 0
                            
                            # print out assumptions violated
                            for x in self.LTLViolationCheck.violated_spec_line_no:
                                if x != 0:
                                    if x not in self.EnvTransRemoved:
                                        self.EnvTransRemoved.append(x)
                                
                               
                            # stop the robot from moving ## needs testing again
                            self.hsub.setVelocity(0,0)
                            
                            # Modify the ltl file based on the enviornment change   
                            self.addStatetoEnvSafety(self.sensor_strategy)
                            
                            # remove line numbers denoted as violated
                            for x in self.EnvTransRemoved:
                                if x in self.LTLViolationCheck.violated_spec_line_no:
                                    self.LTLViolationCheck.violated_spec_line_no.remove(x)
                            
                    else:
                        ###################################
                        ####### FOR ONLY LEANRING #########
                        ###################################
                        # stop the robot from moving 
                        self.hsub.setVelocity(0,0)
                           
                        # Modify the ltl file based on the enviornment change   
                        self.addStatetoEnvSafety(self.sensor_strategy)
            
            else:
                # assumption not violated but sensor state changes. we add in this new state
                self.LTLViolationCheck.append_state_to_LTL(self.strategy.current_state, self.sensor_strategy)

                if env_assumption_hold == False:
                    logging.debug("Value should be True: " + str(env_assumption_hold))
            
                # For print violated safety in the log (update lines violated in every iteration)  
                if len(self.LTLViolationCheck.violated_spec_line_no[:]) == 0 and self.currentViolationLineNo !=self.LTLViolationCheck.violated_spec_line_no[:] and (self.recovery or self.otherRobotStatus): 
                    self.postEvent("RESOLVED", "The specification violation is resolved.")     
            self.currentViolationLineNo = self.LTLViolationCheck.violated_spec_line_no[:] 

            #################################
            
            toc = self.timer_func()

            #self.checkForInternalFlags()

            # Rate limiting of execution and GUI update
            while (toc - tic) < 0.05:
                time.sleep(0.005)
                toc = self.timer_func()

            # Update GUI
            # If rate limiting is disabled in the future add in rate limiting here for the GUI:
            # if show_gui and (timer_func() - last_gui_update_time > 0.05)
            avg_freq = 0.9 * avg_freq + 0.1 * 1 / (toc - tic) # IIR filter
            self.postEvent("FREQ", int(math.ceil(avg_freq)))
            pose = self.hsub.getPose(cached=True)[0:2]
            self.postEvent("POSE", tuple(map(int, self.hsub.coordmap_lab2map(pose))))

            last_gui_update_time = self.timer_func()

        logging.debug("execute.py quitting...")

    # This function is necessary to prevent xmlrpcserver from catching
    # exceptions and eating the tracebacks
    def _dispatch(self, method, args):
        try:
            return getattr(self, method)(*args)
        except:
            traceback.print_exc()
            raise

class RedirectText:
    def __init__(self, event_handler):
        self.event_handler = event_handler

    def write(self, message):
        if message.strip() != "":
            self.event_handler("OTHER", message.strip())

    def flush(self):
        pass


####################################################
# Main function, run when called from command-line #
####################################################

def execute_main(listen_port=None, spec_file=None, aut_file=None, show_gui=False):
    logging.info("Hello. Let's do this!")

    # Create the XML-RPC server
    if listen_port is None:
        # Search for a port we can successfully bind to
        while True:
            listen_port = random.randint(10000, 65535)
            try:
                xmlrpc_server = SimpleXMLRPCServer(("127.0.0.1", listen_port), logRequests=False, allow_none=True)
            except socket.error as e:
                pass
            else:
                break
    else:
        xmlrpc_server = SimpleXMLRPCServer(("127.0.0.1", listen_port), logRequests=False, allow_none=True)

    # Create the execution context object
    e = LTLMoPExecutor()

    # Register functions with the XML-RPC server
    xmlrpc_server.register_instance(e)

    # Kick off the XML-RPC server thread
    XMLRPCServerThread = threading.Thread(target=xmlrpc_server.serve_forever)
    XMLRPCServerThread.daemon = True
    XMLRPCServerThread.start()
    logging.info("Executor listening for XML-RPC calls on http://127.0.0.1:{} ...".format(listen_port))

    # Start the GUI if necessary
    if show_gui:
        # Create a subprocess
        logging.info("Starting GUI window...")
        p_gui = subprocess.Popen([sys.executable, "-u", "-m", "lib.simGUI", str(listen_port)])

        # Wait for GUI to fully load, to make sure that
        # to make sure all messages are redirected
        e.externalEventTargetRegistered.wait()

    if spec_file is not None:
        # Tell executor to load spec & aut
        #if aut_file is None:
        #    aut_file = spec_file.rpartition('.')[0] + ".aut"
        e.initialize(spec_file, aut_file, firstRun=True)

    # Start the executor's main loop in this thread
    e.run()
    
    # Clean up on exit
    logging.info("Waiting for XML-RPC server to shut down...")
    xmlrpc_server.shutdown()
    XMLRPCServerThread.join()
    logging.info("XML-RPC server shutdown complete.  Goodbye.")


### Command-line argument parsing ###

if __name__ == "__main__":
    ### Check command-line arguments

    aut_file = None
    spec_file = None
    show_gui = True
    listen_port = None

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hnp:a:s:", ["help", "no-gui", "xmlrpc-listen-port=", "aut-file=", "spec-file="])
    except getopt.GetoptError:
        logging.exception("Bad arguments")
        usage(sys.argv[0])
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage(sys.argv[0])
            sys.exit()
        elif opt in ("-n", "--no-gui"):
            show_gui = False
        elif opt in ("-p", "--xmlrpc-listen-port"):
            try:
                listen_port = int(arg)
            except ValueError:
                logging.error("Invalid port '{}'".format(arg))
                sys.exit(2)
        elif opt in ("-a", "--aut-file"):
            aut_file = arg
        elif opt in ("-s", "--spec-file"):
            spec_file = arg

    execute_main(listen_port, spec_file, aut_file, show_gui)
