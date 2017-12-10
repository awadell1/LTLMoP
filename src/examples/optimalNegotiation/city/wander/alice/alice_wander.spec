# This is a specification definition file for the LTLMoP toolkit.
# Format details are described at the beginning of each section below.


======== SETTINGS ========

Actions: # List of action propositions and their state (enabled = 1, disabled = 0)

CompileOptions:
neighbour_robot: True
recovery: False
convexify: True
symbolic: False
parser: structured
include_heading: False
winning_livenesses: False
use_region_bit_encoding: True
multi_robot_mode: negotiation
synthesizer: slugs
cooperative_gr1: False
fastslow: False
optimal: twodim
only_realizability: False
decompose: True
interactive: False

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

Cost: # Transition Weights in structured English
# The first line must be of the format: c_d c_t pref
# 	c_d: The delay cost factor
# 	c_t: The transistion cost factor
# 	pref: A cost preference, where > prefers not waiting and < prefers not moving

1 1 <
1.0 square & next(groceryStore)
1.0 groceryStore & next(square)
2.0 square & next(tunnel)
2.0 tunnel & next(square)
2.0 square & next(bridge)
2.0 bridge & next(square)
1.0 square & next(policeStation2)
1.0 policeStation2 & next(square)
1.0 park & next(policeStation1)
1.0 policeStation1 & next(park)
2.0 park & next(tunnel)
2.0 tunnel & next(park)
2.0 park & next(bridge)
2.0 bridge & next(park)
1.0 park & next(postOffice)
1.0 postOffice & next(park)

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

