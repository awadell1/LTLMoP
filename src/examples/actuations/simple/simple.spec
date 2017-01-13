# This is a specification definition file for the LTLMoP toolkit.
# Format details are described at the beginning of each section below.


======== SETTINGS ========

Actions: # List of action propositions and their state (enabled = 1, disabled = 0)
stop_camera, 1
move, 1
stop, 1

CompileOptions:
neighbour_robot: False
convexify: True
parser: structured
symbolic: False
use_region_bit_encoding: True
multi_robot_mode: negotiation
cooperative_gr1: True
fastslow: False
only_realizability: False
recovery: False
include_heading: False
winning_livenesses: False
synthesizer: slugs
decompose: True
interactive: False

CurrentConfigName:
Untitled configuration

Customs: # List of custom propositions

Sensors: # List of sensor propositions and their state (enabled = 1, disabled = 0)
person, 1
sense_object, 1


======== SPECIFICATION ========

GlobalSensors: # Sensors accessible by all robots

OtherRobot: # The other robot in the same workspace

Spec: # Specification in structured English
if you are sensing person then do stop_camera

if you are not sensing sense_object then do move
if you are sensing sense_object then do stop

# corrections
#if you are activating stop_camera then do not get_object
#if you are sensing person then do not move

# mutual exclusion (actions) -explain why
# warning (more than just topic relations)
#if you are not sensing sense_object and you are not activating stop_camera then do move

