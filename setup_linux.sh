# Save the base directory 
cwd=$(pwd)

# Install Basic Requirements
sudo apt-get install default-jre
sudo apt-get install default-jdk
sudo apt-get install python-numpy
sudo apt-get install python-scipy
sudo apt-get install python-wxtools
pip install Polygon2

# Run LTLMop setup file
cd $cwd
echo Runnung LTLMop Setup
python $cwd/dist/setup.py

# Compile SLUGS
echo Compile SLUGS
cd $cwd/src/etc/slugs/src
make

# Return to home
cd $cwd
