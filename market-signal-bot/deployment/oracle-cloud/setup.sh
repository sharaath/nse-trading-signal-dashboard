#!/bin/bash
# ==============================================================================
# ORACLE CLOUD ALWAYS FREE VM SYSTEM INITIALIZATION SCRIPT
# ==============================================================================
# Target OS: Ubuntu 22.04 LTS (OCI Always Free Compute Instance)
# ==============================================================================

set -e

echo "=== [1/5] Updating system packages ==="
sudo apt-get update -y
sudo apt-get upgrade -y

echo "=== [2/5] Installing Docker Engine & Docker Compose ==="
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker official GPG key
sudo mkdir -p /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
fi

# Set up repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker daemon
sudo systemctl enable docker
sudo systemctl start docker

# Add current user to docker group to run without sudo
sudo usermod -aG docker $USER

echo "=== [3/5] Setting up Oracle Cloud VM Firewall Rules (iptables) ==="
# Oracle VMs have strict default iptables rules blocking incoming traffic.
# Expose only FastAPI API (8000) and React Frontend (5173). Keep PostgreSQL private.
sudo iptables -I INPUT 6 -p tcp --dport 8000 -m state --state NEW -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 5173 -m state --state NEW -j ACCEPT

# Save iptables rules so they persist across VM reboots
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save

echo "=== [4/5] Creating Default Environment Variables file ==="
if [ ! -f "../../.env" ]; then
    cp ../../.env.example ../../.env
    echo "Created default .env file in project root. Please open and edit with your credentials."
else
    echo ".env file already exists. Skipping default creation."
fi

echo "=== [5/5] Setup completed successfully! ==="
echo "Please LOG OUT and LOG BACK IN to apply Docker group permissions."
echo "Then edit the .env file in the project root and run 'docker compose up --build -d'."
