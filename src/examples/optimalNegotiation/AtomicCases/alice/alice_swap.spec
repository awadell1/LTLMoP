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
../swap.region

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
bob_r1, 1
bob_r2, 1
bob_r3, 1
bob_r4, 1


======== SPECIFICATION ========

Cost: # Transition Weights in structured English
# The first line must be of the format: c_d c_t pref
# 	c_d: The delay cost factor
# 	c_t: The transition cost factor
# 	pref: A cost preference, where < prefers waiting and > prefers moving

1 0 <
1.0 r1 & next(r2)
1.0 r1 & next(r3)
1.0 r4 & next(r2)
1.0 r4 & next(r3)
1.0 r2 & next(r1)
1.0 r3 & next(r1)
1.0 r2 & next(r4)
1.0 r3 & next(r4)

GlobalSensors: # Sensors accessible by all robots

OtherRobot: # The other robot in the same workspace
bob

RegionMapping: # Mapping between region names and their decomposed counterparts
r4 = p2
r1 = p5
r2 = p4
r3 = p3
others = 

Spec: # Specification in structured English
Robot starts in r1
Env starts with bob_r4

# Environment Assumptions
if you were in r1 then do not bob_r2
if you were in r1 then do not bob_r3
if you were in r2 then do not bob_r4
if you were in r3 then do not bob_r4

visit r4

