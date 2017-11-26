#!/bin/bash
specFile="examples/optimalNegotiation/oneRobot/oneRobot.spec"
autFile="examples/optimalNegotiation/oneRobot/oneRobot.aut"
cwd=$(pwd)
cd ../../
python specEditor.py $specFile -c -r
cd $cwd