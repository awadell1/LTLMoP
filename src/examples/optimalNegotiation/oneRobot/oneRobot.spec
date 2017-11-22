# This is a specification definition file for the LTLMoP toolkit.
# Format details are described at the beginning of each section below.


======== SETTINGS ========

Actions: # List of action propositions and their state (enabled = 1, disabled = 0)
sad, 1

CompileOptions:
synthesizer: slugs
fastslow: False
convexify: True
optimal: twodim
parser: structured
symbolic: False
decompose: True
use_region_bit_encoding: True

CurrentConfigName:
Basic Simulation

Customs: # List of custom propositions
_l_a_c_v_1
_is_infty_cost_Pre

RegionFile: # Relative path of region description file
oneRobot.regions

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
isSnow, 1
isLine, 1


======== SPECIFICATION ========

Cost: # Transistion Weights in structured English
0 1 >
2.0 collegetown & isSnow
1.0 duffield & !isLine
1.1 duffield & isLine

RegionMapping: # Mapping between region names and their decomposed counterparts
office = p3
collegetown = p6
starbucks = p2
others = p1
duffield = p5
between$starbucks$and$office$ = p5, p6

Spec: # Specification in structured English
# Initial conditions
Env starts with false
Robot starts in office with false

# Assumptions about the environment
Visit !isLine

# Define Safety
# If you are sensing isLine then do sad
If between starbucks and office then do sad

# Define Liveness
visit starbucks unless isLine
visit office

