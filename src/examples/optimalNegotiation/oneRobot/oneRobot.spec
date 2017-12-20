# This is a specification definition file for the LTLMoP toolkit.
# Format details are described at the beginning of each section below.


======== SETTINGS ========

Actions: # List of action propositions and their state (enabled = 1, disabled = 0)
sad, 1

CompileOptions:
neighbour_robot: False
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
Basic Simulation

Customs: # List of custom propositions

RegionFile: # Relative path of region description file
oneRobot.regions

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
isSnow, 1
isLine, 1


======== SPECIFICATION ========

Cost: # Transition Weights in structured English
# The first line must be of the format: c_d c_t pref
# 	c_d: The delay cost factor
# 	c_t: The transition cost factor
# 	pref: A cost preference, where > prefers not waiting and < prefers not moving

0 1 >
2.0 collegetown & isSnow

GlobalSensors: # Sensors accessible by all robots

OtherRobot: # The other robot in the same workspace

RegionMapping: # Mapping between region names and their decomposed counterparts
office = p4
collegetown = p6
starbucks = p3
others = p1
duffield = p5

Spec: # Specification in structured English
# Initial conditions
Env starts with false
Robot starts in office with false

# Assumptions about the environment
Visit !isLine

# Define Safety
# If you are sensing isLine then do sad

# Define Liveness
visit starbucks unless isLine
visit office

