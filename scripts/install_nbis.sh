#!/bin/bash

set -e

echo "Installing NBIS..."

# Install dependencies
sudo apt-get update
sudo apt-get install -y build-essential libpng-dev libjpeg-dev wget unzip

# Download NBIS
cd /tmp
rm -rf Rel_5.0.0 nbis_v5_0_0.zip
wget https://nigos.nist.gov/nist/nbis/nbis_v5_0_0.zip
unzip nbis_v5_0_0.zip
cd Rel_5.0.0

# Run setup
./setup.sh /usr/local/nbis --without-X11

# Build common libraries
echo "Building common libraries..."
cd commonnbis
make config
make it
sudo make install
cd ..

# Create bin directory BEFORE installing (critical fix)
sudo mkdir -p /usr/local/nbis/bin

# Build and install mindtct
echo "Building mindtct..."
cd mindtct
make config
make it
sudo make install
cd ..

# Build and install bozorth3
echo "Building bozorth3..."
cd bozorth3
make config
make it
sudo make install
cd ..

# Add to PATH
echo 'export PATH=$PATH:/usr/local/nbis/bin' | sudo tee /etc/profile.d/nbis.sh
export PATH=$PATH:/usr/local/nbis/bin

# Verify
echo ""
echo "Verifying installation..."
if [ -f /usr/local/nbis/bin/mindtct ] && [ -f /usr/local/nbis/bin/bozorth3 ]; then
    echo "NBIS installed successfully!"
    echo "  mindtct: /usr/local/nbis/bin/mindtct"
    echo "  bozorth3: /usr/local/nbis/bin/bozorth3"
else
    echo "Installation failed"
    exit 1
fi