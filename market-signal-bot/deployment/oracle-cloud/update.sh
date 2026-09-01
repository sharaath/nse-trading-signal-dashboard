#!/bin/bash
# ==============================================================================
# ORACLE CLOUD APPLICATION UPDATE & INTEGRATION SCRIPT
# ==============================================================================

set -e

# Navigate to project root directory containing docker-compose.yml
cd "$(dirname "$0")/../.."

echo "=== [1/4] Pulling latest updates from Git ==="
git pull origin main || echo "Git repository not configured, skipping pull."

echo "=== [2/4] Rebuilding and Restarting Docker Containers ==="
# Boot containers in detached mode, rebuilding any changed images
docker compose up --build -d

echo "=== [3/4] Cleaning up unused Docker caches ==="
# Oracle VMs have limited free storage space (default boot volume 47GB).
# Clean up obsolete build steps and dangling images.
docker image prune -f

echo "=== [4/4] Update process complete! ==="
docker compose ps
