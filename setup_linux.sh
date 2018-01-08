# Save the base directory 
cwd=$(pwd)

# Install Basic Requirements
echo Root access requested to install dependancies
sudo apt-get install default-jre -y
sudo apt-get install default-jdk -y
sudo apt-get install python-numpy -y
sudo apt-get install python-scipy -y
sudo apt-get install python-wxtools -y
sudo apt-get install libboost-dev -y
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
