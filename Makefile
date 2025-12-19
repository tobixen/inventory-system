# Inventory System Makefile
# Quick commands for managing the inventory system

.PHONY: help install install-services start stop restart status logs logs-chat logs-web enable disable

# Default target
help:
	@echo "Inventory System - Available Commands"
	@echo ""
	@echo "Installation:"
	@echo "  make install           Install systemd services (requires ANTHROPIC_API_KEY)"
	@echo "  make install-services  Install service files to ~/.config/systemd/user/"
	@echo ""
	@echo "Service Management:"
	@echo "  make start             Start both web and chat servers"
	@echo "  make stop              Stop both servers"
	@echo "  make restart           Restart both servers"
	@echo "  make status            Show status of both servers"
	@echo "  make enable            Enable auto-start on boot"
	@echo "  make disable           Disable auto-start"
	@echo ""
	@echo "Logs:"
	@echo "  make logs              Show logs for both servers"
	@echo "  make logs-chat         Show chat server logs"
	@echo "  make logs-web          Show web server logs"
	@echo ""
	@echo "Individual Services:"
	@echo "  make start-chat        Start chat server only"
	@echo "  make start-web         Start web server only"
	@echo "  make stop-chat         Stop chat server only"
	@echo "  make stop-web          Stop web server only"

# Install services
install-services:
	@echo "📦 Installing systemd service files..."
	@mkdir -p ~/.config/systemd/user
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "⚠️  Warning: ANTHROPIC_API_KEY not set"; \
		echo "   The chat service won't work until you set it"; \
		echo "   Run: make set-api-key API_KEY=your-key-here"; \
	fi
	@sed "s|ANTHROPIC_API_KEY=|ANTHROPIC_API_KEY=$$ANTHROPIC_API_KEY|g" systemd/inventory-chat.service > ~/.config/systemd/user/inventory-chat.service
	@cp systemd/inventory-web.service ~/.config/systemd/user/
	@systemctl --user daemon-reload
	@echo "✅ Services installed!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Start services: make start"
	@echo "  2. Enable auto-start: make enable"
	@echo "  3. Check status: make status"

# Set API key
set-api-key:
	@if [ -z "$(API_KEY)" ]; then \
		echo "❌ Error: API_KEY not provided"; \
		echo "   Usage: make set-api-key API_KEY=your-key-here"; \
		exit 1; \
	fi
	@sed -i "s|ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$(API_KEY)|g" ~/.config/systemd/user/inventory-chat.service
	@systemctl --user daemon-reload
	@echo "✅ API key updated!"
	@echo "   Restart chat service: make restart-chat"

# Start services
start:
	@echo "🚀 Starting inventory services..."
	@systemctl --user start inventory-web.service
	@systemctl --user start inventory-chat.service
	@echo "✅ Services started!"
	@echo ""
	@$(MAKE) status

start-web:
	@systemctl --user start inventory-web.service
	@echo "✅ Web server started on http://localhost:8000"

start-chat:
	@systemctl --user start inventory-chat.service
	@echo "✅ Chat server started on http://localhost:8765"

# Stop services
stop:
	@echo "🛑 Stopping inventory services..."
	@systemctl --user stop inventory-web.service inventory-chat.service
	@echo "✅ Services stopped!"

stop-web:
	@systemctl --user stop inventory-web.service
	@echo "✅ Web server stopped"

stop-chat:
	@systemctl --user stop inventory-chat.service
	@echo "✅ Chat server stopped"

# Restart services
restart:
	@echo "🔄 Restarting inventory services..."
	@systemctl --user restart inventory-web.service inventory-chat.service
	@echo "✅ Services restarted!"
	@$(MAKE) status

restart-web:
	@systemctl --user restart inventory-web.service
	@echo "✅ Web server restarted"

restart-chat:
	@systemctl --user restart inventory-chat.service
	@echo "✅ Chat server restarted"

# Status
status:
	@echo "📊 Inventory Services Status:"
	@echo ""
	@echo "Web Server (http://localhost:8000):"
	@systemctl --user status inventory-web.service --no-pager --lines=0 || true
	@echo ""
	@echo "Chat Server (http://localhost:8765):"
	@systemctl --user status inventory-chat.service --no-pager --lines=0 || true
	@echo ""
	@echo "Access your inventory at: http://localhost:8000/search.html"

# Enable auto-start
enable:
	@systemctl --user enable inventory-web.service inventory-chat.service
	@echo "✅ Services will auto-start on boot"

# Disable auto-start
disable:
	@systemctl --user disable inventory-web.service inventory-chat.service
	@echo "✅ Auto-start disabled"

# Logs
logs:
	@echo "📜 Showing logs for both services (Ctrl+C to exit)..."
	@journalctl --user -u inventory-web.service -u inventory-chat.service -f

logs-web:
	@echo "📜 Web server logs (Ctrl+C to exit)..."
	@journalctl --user -u inventory-web.service -f

logs-chat:
	@echo "📜 Chat server logs (Ctrl+C to exit)..."
	@journalctl --user -u inventory-chat.service -f

# Installation shortcut
install: install-services
	@echo ""
	@echo "🎉 Installation complete!"
	@echo ""
	@echo "Quick start:"
	@echo "  1. make start    # Start both servers"
	@echo "  2. Open http://localhost:8000/search.html in your browser"
	@echo "  3. Click the chat button (💬) to start chatting"
