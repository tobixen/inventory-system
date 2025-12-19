# Installation & Setup Guide

This guide shows how to set up the inventory system with systemd services for easy management.

## Prerequisites

1. **Install the package:**
   ```bash
   pip install -e /home/tobias/inventory-system
   ```

2. **Install chat dependencies:**
   ```bash
   pip install fastapi uvicorn anthropic
   ```

3. **Get your Claude API key:**
   - Visit https://console.anthropic.com/
   - Create an API key
   - Copy it for the next step

## Quick Setup

### 1. Set your API key:
```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```

### 2. Install systemd services:
```bash
cd /home/tobias/inventory-system
make install-services
```

This will:
- Create service files in `~/.config/systemd/user/`
- Set your API key in the chat service
- Reload systemd

### 3. Start the services:
```bash
make start
```

### 4. Access your inventory:
Open http://localhost:8000/search.html in your browser

## Makefile Commands

### Service Management
```bash
make start          # Start both web and chat servers
make stop           # Stop both servers
make restart        # Restart both servers
make status         # Show status of both servers
make enable         # Enable auto-start on boot
make disable        # Disable auto-start
```

### Individual Services
```bash
make start-chat     # Start chat server only
make start-web      # Start web server only
make stop-chat      # Stop chat server only
make stop-web       # Stop web server only
make restart-chat   # Restart chat server only
make restart-web    # Restart web server only
```

### Logs
```bash
make logs           # Show logs for both servers (follow mode)
make logs-chat      # Show chat server logs only
make logs-web       # Show web server logs only
```

### Updating API Key
```bash
make set-api-key API_KEY=your-new-key-here
make restart-chat   # Restart to apply changes
```

## Manual Setup (without Makefile)

If you prefer to set up manually:

### 1. Copy service files:
```bash
mkdir -p ~/.config/systemd/user
cp systemd/inventory-web.service ~/.config/systemd/user/
cp systemd/inventory-chat.service ~/.config/systemd/user/
```

### 2. Edit chat service to add your API key:
```bash
nano ~/.config/systemd/user/inventory-chat.service
# Change: Environment="ANTHROPIC_API_KEY="
# To:     Environment="ANTHROPIC_API_KEY=your-key-here"
```

### 3. Reload systemd:
```bash
systemctl --user daemon-reload
```

### 4. Start services:
```bash
systemctl --user start inventory-web.service
systemctl --user start inventory-chat.service
```

### 5. Enable auto-start (optional):
```bash
systemctl --user enable inventory-web.service
systemctl --user enable inventory-chat.service
```

## Verifying Installation

### Check service status:
```bash
systemctl --user status inventory-web.service
systemctl --user status inventory-chat.service
```

### Check if servers are running:
```bash
# Web server
curl http://localhost:8000/search.html

# Chat server health check
curl http://localhost:8765/health
```

### View logs:
```bash
journalctl --user -u inventory-chat.service -n 50
journalctl --user -u inventory-web.service -n 50
```

## Troubleshooting

### Chat service fails to start
1. **Check API key is set:**
   ```bash
   systemctl --user cat inventory-chat.service | grep ANTHROPIC_API_KEY
   ```

2. **Check logs:**
   ```bash
   journalctl --user -u inventory-chat.service -n 50
   ```

3. **Verify inventory.json exists:**
   ```bash
   ls -lh ~/furusetalle9/inventory/inventory.json
   ```

### Port already in use
If ports 8000 or 8765 are already in use, edit the service files:

```bash
nano ~/.config/systemd/user/inventory-web.service
# Change: ExecStart=/usr/bin/inventory-system serve
# To:     ExecStart=/usr/bin/inventory-system serve --port 8080

nano ~/.config/systemd/user/inventory-chat.service
# Change: ExecStart=/usr/bin/inventory-system chat
# To:     ExecStart=/usr/bin/inventory-system chat --port 8866

systemctl --user daemon-reload
systemctl --user restart inventory-web.service inventory-chat.service
```

Also update the chat server URL in search.html:
```javascript
const CHAT_SERVER_URL = 'http://localhost:8866';
```

## Uninstallation

### Stop and disable services:
```bash
make stop
make disable
```

### Remove service files:
```bash
rm ~/.config/systemd/user/inventory-web.service
rm ~/.config/systemd/user/inventory-chat.service
systemctl --user daemon-reload
```

## Usage

Once installed and running:

1. **Access web interface:**
   - Open http://localhost:8000/search.html

2. **Use the chat:**
   - Click the green chat button (💬) in bottom-right corner
   - Ask questions about your inventory
   - Examples:
     - "What's in box A78?"
     - "Where are my winter clothes?"
     - "Show me all boxes with skiing equipment"

3. **Update inventory:**
   ```bash
   cd ~/furusetalle9/inventory
   # Edit inventory.md
   inventory-system parse inventory.md
   make restart  # Reload with new data
   ```

## Next Steps

- See `README.md` for inventory system documentation
- See `CHANGELOG.md` for recent changes
- Phase 2 will add write operations (update inventory through chat)
