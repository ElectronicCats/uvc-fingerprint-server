#!/bin/bash
# Checador Installation Script

set -e

echo "=========================================="
echo "Checador Installation"
echo "=========================================="

# Check if running as root for system install
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo ./install.sh)"
    exit 1
fi

# Get the actual user who called sudo
REAL_USER=${SUDO_USER:-$USER}
INSTALL_DIR="/opt/checador"

echo ""
echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y \
    python3 python3-pip \
    build-essential \
    libopencv-dev python3-opencv \
    v4l-utils sqlite3 \
    libpng-dev libjpeg-dev \
    wget unzip

echo ""
echo "Step 2: Installing NBIS..."
if ! command -v mindtct &> /dev/null || ! command -v bozorth3 &> /dev/null; then
    echo "NBIS not found, installing..."
    cd /tmp
    rm -rf Rel_5.0.0 nbis_v5_0_0.zip
    wget https://nigos.nist.gov/nist/nbis/nbis_v5_0_0.zip
    unzip nbis_v5_0_0.zip
    cd Rel_5.0.0
    
    # Fix OpenJPEG compilation errors
    sed -i '1i#include <unistd.h>' openjp2/src/lib/openjp2/src/bin/jp2/opj_compress.c
    sed -i '1i#include <unistd.h>' openjp2/src/lib/openjp2/src/bin/jp2/opj_decompress.c
    sed -i '1i#include <unistd.h>' openjp2/src/lib/openjp2/src/bin/jp2/opj_dump.c
    
    ./setup.sh /usr/local/nbis --without-X11
    
    # Build common libraries
    cd commonnbis
    make config
    make it
    make install
    cd ..
    
    # Create bin directory
    mkdir -p /usr/local/nbis/bin
    
    # Build mindtct
    cd mindtct
    make config
    make it
    make install
    cd ..
    
    # Build bozorth3
    cd bozorth3
    make config
    make it
    make install
    cd ..
    
    # Add to PATH
    echo 'export PATH=$PATH:/usr/local/nbis/bin' | tee /etc/profile.d/nbis.sh
    export PATH=$PATH:/usr/local/nbis/bin
    
    echo "✓ NBIS installed successfully"
else
    echo "✓ NBIS already installed"
fi

echo ""
echo "Step 3: Installing Python dependencies..."
cd "$INSTALL_DIR"
pip3 install --break-system-packages -r requirements.txt
pip3 install --break-system-packages -e .

echo ""
echo "Step 4: Creating directories..."
mkdir -p /etc/checador
mkdir -p /var/lib/checador/{templates,temp}
chown -R $REAL_USER:$REAL_USER /var/lib/checador

echo ""
echo "Step 5: Installing configuration..."
if [ ! -f /etc/checador/config.toml ]; then
    cp config.example.toml /etc/checador/config.toml
    chown $REAL_USER:$REAL_USER /etc/checador/config.toml
    chmod 600 /etc/checador/config.toml
    echo "✓ Config file created at /etc/checador/config.toml"
    echo "  IMPORTANT: Edit this file and set your admin password hash!"
else
    echo "✓ Config file already exists"
fi

echo ""
echo "Step 6: Installing CLI tool..."
cp scripts/checador-cli /usr/local/bin/checador
chmod +x /usr/local/bin/checador
echo "✓ CLI tool installed"

echo ""
echo "Step 7: Installing systemd service..."
cp checador.service /etc/systemd/system/
systemctl daemon-reload
echo "✓ Service installed"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Generate admin password hash:"
echo "   python3 -c \"from argon2 import PasswordHasher; print(PasswordHasher().hash('your_password'))\""
echo ""
echo "2. Edit config and add password hash:"
echo "   sudo nano /etc/checador/config.toml"
echo ""
echo "3. Calibrate camera (run service manually first):"
echo "   sudo systemctl start checador"
echo "   # Open browser to http://<device-ip>:8000/calibration"
echo "   # Draw ROI rectangle, click Save"
echo ""
echo "4. Enable service to start on boot:"
echo "   sudo systemctl enable checador"
echo ""
echo "5. Check service status:"
echo "   sudo systemctl status checador"
echo ""
echo "CLI commands available:"
echo "   checador users list"
echo "   checador camera test"
echo "   checador export --output /tmp/punches.csv"
echo ""