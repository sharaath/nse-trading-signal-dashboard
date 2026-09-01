#!/bin/bash
# ==============================================================================
# ORACLE CLOUD APPLICATION TELEMETRY & HEALTH VERIFY SCRIPT
# ==============================================================================

# Parse colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0;0m'

echo "=== Oracle Cloud VM Telemetry Check ==="
echo "Date: $(date)"
echo "---------------------------------------"

# 1. Verify Docker containers are running
echo "Checking Docker containers..."
containers=("msb-db" "msb-api" "msb-worker" "msb-bot" "msb-frontend")
all_running=true

for c in "${containers[@]}"; do
    state=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "MISSING")
    if [ "$state" == "running" ]; then
        echo -e "Container $c: ${GREEN}RUNNING${NC}"
    else
        echo -e "Container $c: ${RED}FAILED (${state})${NC}"
        all_running=false
    fi
done

# 2. Query /health API response
echo "---------------------------------------"
echo "Querying API Health Check endpoint..."
health_resp=$(curl -s --max-time 5 http://localhost:8000/health || echo "FAILED")

if [ "$health_resp" == "FAILED" ]; then
    echo -e "API Server: ${RED}UNREACHABLE (Port 8000)${NC}"
else
    # Extract keys using python to avoid jq dependency on OCI Linux minimal install
    python3 -c "
import sys, json
try:
    data = json.loads(sys.argv[1])
    print(f'API Server: {GREEN}HEALTHY{NC}')
    print(f'Database:   ' + (f'{GREEN}HEALTHY{NC}' if data.get(\"database\") == \"HEALTHY\" else f'{RED}UNHEALTHY{NC}'))
    print(f'Worker:     ' + (f'{GREEN}RUNNING{NC}' if data.get(\"worker\") == \"RUNNING\" else f'{RED}STOPPED{NC}'))
    print(f'Provider:   ' + data.get(\"provider\", \"UNKNOWN\").upper())
    print(f'WebSocket:  ' + (f'{GREEN}CONNECTED{NC}' if data.get(\"websocket\") == \"CONNECTED\" else f'{RED}DISCONNECTED{NC}'))
    print(f'Data Age:   ' + data.get(\"data_age\", \"N/A\"))
    print(f'Latency:    ' + data.get(\"latency\", \"N/A\"))
    print(f'Telegram:   ' + (f'{GREEN}CONNECTED{NC}' if data.get(\"telegram\") == \"CONNECTED\" else f'{RED}DISCONNECTED{NC}'))
    print(f'System Mode:' + f' {GREEN}' + data.get(\"mode\", \"PAPER\") + f'{NC}')
    print(f'Real Orders:' + (f' {RED}ENABLED (CRITICAL ERROR){NC}' if data.get(\"real_orders_enabled\") else f' {GREEN}DISABLED{NC}'))
    print(f'Eligibility:' + (f' {GREEN}ELIGIBLE{NC}' if data.get(\"trading_eligibility\") else f' {RED}BLOCKED{NC}'))
except Exception as e:
    print('Failed to parse health JSON:', e)
" "$health_resp"
fi
echo "---------------------------------------"
