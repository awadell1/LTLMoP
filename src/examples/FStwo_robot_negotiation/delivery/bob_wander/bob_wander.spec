# This is a specification definition file for the LTLMoP toolkit.
# Format details are described at the beginning of each section below.


======== SETTINGS ========

Actions: # List of action propositions and their state (enabled = 1, disabled = 0)

CompileOptions:
neighbour_robot: True
convexify: True
parser: structured
symbolic: False
use_region_bit_encoding: True
multi_robot_mode: negotiation
cooperative_gr1: True
fastslow: True
only_realizability: False
recovery: True
include_heading: False
winning_livenesses: False
synthesizer: slugs
decompose: True
interactive: True

CurrentConfigName:
basicSim

Customs: # List of custom propositions

RegionFile: # Relative path of region description file
../threeCorridors.regions

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
alice_hallwayTop, 1
alice_office, 1
alice_reception, 1
alice_cafe, 1
alice_emergencyExit, 1
alice_hallwayBottom, 1
alice_hallwayCentral, 1
alice_library, 1
alice_atrium, 1
alice_storageBottom, 1
alice_storageTop, 1


======== SPECIFICATION ========

GlobalSensors: # Sensors accessible by all robots

OtherRobot: # The other robot in the same workspace
alice

RegionMapping: # Mapping between region names and their decomposed counterparts
emergencyExit = p14
hallwayBottomL = p11
hallwayCentralR = p8
office = p4
hallwayCentralL = p9
storageTop = p1
others = 
hallwayTopR = p6
library = p5
hallwayTopL = p7
reception = p3
storageBottom = p2
atrium = p16
cafe = p15
hallwayBottomR = p10

Spec: # Specification in structured English
Robot starts in emergencyExit
Environment starts with alice_library

visit hallwayTop
visit hallwayBottom
#visit hallwayCentral

# other robot's assumptions
if you have finished atrium then do not (alice_atrium or alice_storageTop)
if you have finished storageTop then do not (alice_storageTop or alice_hallwayTop)
if you have finished hallwayTop then do not (alice_hallwayTop or alice_emergencyExit)
if you have finished emergencyExit then do not (alice_emergencyExit or alice_reception)
if you have finished reception then do not (alice_reception or alice_cafe)
if you have finished cafe then do not (alice_cafe or alice_hallwayBottom)
if you have finished hallwayBottom then do not (alice_hallwayBottom or alice_storageBottom)
if you have finished storageBottom then do not (alice_atrium or alice_storageBottom)


# sysTrans from nego
###if you are sensing alice_library then do not (finished library or finished atrium)
#if you are sensing alice_atrium then do not (finished library or finished atrium or finished hallwayCentral)
#####if you are sensing alice_hallwayCentral then do not (finished library or finished atrium or finished hallwayCentral or finished reception or finished reception or finished office)
#if you are sensing alice_reception then do not (finished hallwayCentral or finished reception or finished office)
#####if you are sensing alice_office then do not (finished office or finished reception)

