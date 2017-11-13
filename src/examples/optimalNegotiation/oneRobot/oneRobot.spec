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
collegetown = p6
duffield = p5
starbucks = p3
office = p4
others = p1

Spec: # Specification in structured English
# Initial conditions
Env starts with false
Robot starts in office with false

# Assumptions about the environment
Visit !isLine

# Define Safety
If you are sensing isLine then do sad

# Define Liveness
visit starbucks unless isLine
visit office

