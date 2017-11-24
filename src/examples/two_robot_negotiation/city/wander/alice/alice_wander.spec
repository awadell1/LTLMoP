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
fastslow: False
only_realizability: False
recovery: True
include_heading: False
winning_livenesses: False
synthesizer: slugs
decompose: True
interactive: True

CurrentConfigName:
alice

Customs: # List of custom propositions

RegionFile: # Relative path of region description file
../../city.regions

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
bob_policeStation2, 1
bob_groceryStore, 1
bob_bridge, 1
bob_tunnel, 1
bob_postOffice, 1
bob_park, 1
bob_policeStation1, 1
bob_square, 1


======== SPECIFICATION ========

GlobalSensors: # Sensors accessible by all robots

OtherRobot: # The other robot in the same workspace
bob

RegionMapping: # Mapping between region names and their decomposed counterparts
bridge = p9
square = p2
policeStation1 = p6
policeStation2 = p5
tunnel = p1
park = p7
postOffice = p4
others = 
groceryStore = p8

Spec: # Specification in structured English
Robot starts in bridge
Env starts with bob_groceryStore

# Environment Assumptions
if you were in bridge then do not bob_square
if you were in square then do not bob_groceryStore

visit groceryStore

