#!/usr/bin/env bash
# start.sh — launch Factory.io and the full SCADA stack together
# Run as your normal user: ./start.sh

WINE="/opt/wine-cachyos/bin/wine"
FACTORYIO="/home/von/.wine-factoryio/drive_c/Program Files (x86)/Real Games/Factory IO/Factory IO.exe"
WINEPREFIX="/home/von/.wine-factoryio"

# Allow Docker containers (172.18.0.0/16) to reach Factory.io on the host.
# This rule is not persistent — we re-apply it on every start.
echo "Applying iptables rule for Docker → Factory.io..."
sudo iptables -C INPUT -s 172.18.0.0/16 -p tcp --dport 502 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport 502 -j ACCEPT

# Launch Factory.io as the current user — stderr to /dev/null to suppress Wine debug spam
echo "Starting Factory.io..."
WINEPREFIX="$WINEPREFIX" "$WINE" "$FACTORYIO" 2>/dev/null &
FACTORYIO_PID=$!

echo "Factory.io started (PID $FACTORYIO_PID)"
echo "Waiting 8 seconds for Factory.io to initialise..."
sleep 8

# Start the Docker stack
echo "Starting SCADA stack..."
sudo docker compose up --remove-orphans "$@"

# When docker compose exits, clean up Factory.io too
echo "Stopping Factory.io..."
kill $FACTORYIO_PID 2>/dev/null
