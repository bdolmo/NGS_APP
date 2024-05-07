#!/bin/bash

# Define variables for the app directory and queue name
APP_DIR="/home/udmmp/NGS_APP"
QUEUE_NAME="default"
WORKER_SCRIPT="rq worker $QUEUE_NAME"
NGS_SCRIPT="python $APP_DIR/NGS.py"

# Change to the correct directory
cd $APP_DIR

# Function to check if the RQ worker is running
check_rq_worker() {
  if pgrep -f "$WORKER_SCRIPT" > /dev/null; then
    return 0  # Worker is running
  else
    return 1  # Worker is not running
  fi
}

# Function to check if NGS.py is running
check_ngs() {
  if pgrep -f "$NGS_SCRIPT" > /dev/null; then
    return 0  # NGS.py is running
  else
    return 1  # NGS.py is not running
  fi
}

# Ensure NGS.py is running
if check_ngs; then
  echo "NGS.py is already running."
else
  echo "Starting NGS.py..."
  $NGS_SCRIPT &
fi

# Infinite loop to ensure the RQ worker runs/restarts only when it's not already running
while true; do
  if check_rq_worker; then
    echo "RQ worker is already running."
  else
    echo "Starting RQ worker..."
    $WORKER_SCRIPT
    echo "RQ worker has stopped unexpectedly."
  fi
  sleep 5  # Delay for 5 seconds before checking again
done

