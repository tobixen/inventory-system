# Inventory System Makefile
# Quick commands for managing inventory instances

.PHONY: help install install-templates create-instance start stop restart status logs enable disable list-instances

# Configuration
INSTANCE ?= furuset
INSTANCES = furuset solveig

# Default target
help:
	@echo "Inventory System - Multi-Instance Management"
	@echo ""
	@echo "Installation:"
	@echo "  make install                       Install Python package in venv"
	@echo "  make install-templates             Install systemd template services"
	@echo "  make create-instance INSTANCE=name Create new instance (user + config)"
	@echo ""
	@echo "Instance Management:"
	@echo "  make start INSTANCE=name           Start instance (default: furuset)"
	@echo "  make stop INSTANCE=name            Stop instance"
	@echo "  make restart INSTANCE=name         Restart instance"
	@echo "  make status INSTANCE=name          Show instance status"
	@echo "  make enable INSTANCE=name          Enable auto-start on boot"
	@echo "  make disable INSTANCE=name         Disable auto-start"
	@echo ""
	@echo "All Instances:"
	@echo "  make start-all                     Start all instances"
	@echo "  make stop-all                      Stop all instances"
	@echo "  make restart-all                   Restart all instances"
	@echo "  make status-all                    Show all instances status"
	@echo "  make enable-all                    Enable all instances"
	@echo ""
	@echo "Logs:"
	@echo "  make logs INSTANCE=name            Show logs for instance"
	@echo "  make logs-api INSTANCE=name       Show chat logs only"
	@echo "  make logs-web INSTANCE=name        Show web logs only"
	@echo ""
	@echo "Available instances: $(INSTANCES)"
	@echo "Default instance: $(INSTANCE)"

# Install Python package and dependencies
install:
	@echo "📦 Installing inventory-system Python package..."
	@python3 -m venv venv
	@venv/bin/pip install --upgrade pip
	@venv/bin/pip install .
	@echo "✅ Python package installed in venv/"

# Install template services
install-templates:
	@echo "📦 Installing systemd template services..."
	@sudo cp systemd/inventory-web@.service /etc/systemd/system/
	@sudo cp systemd/inventory-api@.service /etc/systemd/system/
	@sudo mkdir -p /etc/inventory-system
	@sudo systemctl daemon-reload
	@echo "✅ Template services installed!"
	@echo ""
	@echo "Next: Create instances with 'make create-instance INSTANCE=name'"

# Create instance
create-instance:
	@# Check if templates are installed
	@if [ ! -f "/etc/systemd/system/inventory-web@.service" ]; then \
		echo "⚠️  Systemd templates not installed. Installing now..."; \
		echo ""; \
		$(MAKE) install-templates; \
		echo ""; \
	fi
	@echo "📋 Creating instance: $(INSTANCE)"
	@echo ""
	@# Ensure config directory exists
	@sudo mkdir -p /etc/inventory-system
	@# Check if config already exists
	@if [ -f "/etc/inventory-system/$(INSTANCE).conf" ]; then \
		echo "⚠️  Config already exists: /etc/inventory-system/$(INSTANCE).conf"; \
		read -p "Overwrite? [y/N] " answer; \
		if [ "$$answer" != "y" ]; then \
			echo "Aborted."; \
			exit 1; \
		fi; \
	fi
	@# Create user
	@echo "👤 Creating user: inventory-$(INSTANCE)..."
	@if id inventory-$(INSTANCE) &>/dev/null; then \
		echo "   User already exists"; \
	else \
		sudo useradd -r -s /usr/bin/nologin -d /nonexistent inventory-$(INSTANCE); \
		echo "✅ User created"; \
	fi
	@# Create config from example
	@if [ -f "systemd/$(INSTANCE).conf.example" ]; then \
		echo "📝 Installing config from example..."; \
		sudo cp systemd/$(INSTANCE).conf.example /etc/inventory-system/$(INSTANCE).conf; \
	else \
		echo "📝 Creating default config..."; \
		echo "# Inventory System Configuration for $(INSTANCE)" | sudo tee /etc/inventory-system/$(INSTANCE).conf > /dev/null; \
		echo "INVENTORY_PATH=/path/to/$(INSTANCE)/inventory" | sudo tee -a /etc/inventory-system/$(INSTANCE).conf > /dev/null; \
		echo "WEB_PORT=8000" | sudo tee -a /etc/inventory-system/$(INSTANCE).conf > /dev/null; \
		echo "API_PORT=8765" | sudo tee -a /etc/inventory-system/$(INSTANCE).conf > /dev/null; \
		echo "ANTHROPIC_API_KEY=" | sudo tee -a /etc/inventory-system/$(INSTANCE).conf > /dev/null; \
	fi
	@echo "✅ Config created: /etc/inventory-system/$(INSTANCE).conf"
	@echo ""
	@echo "⚠️  IMPORTANT: Edit the config file:"
	@echo "   sudo nano /etc/inventory-system/$(INSTANCE).conf"
	@echo ""
	@echo "Then set permissions on inventory directory:"
	@echo "   sudo chgrp -R inventory-$(INSTANCE) /path/to/inventory"
	@echo "   sudo chmod -R g+rX /path/to/inventory"
	@echo ""
	@echo "Then start the instance:"
	@echo "   make start INSTANCE=$(INSTANCE)"

# Set permissions for instance
set-permissions:
	@if [ ! -f "/etc/inventory-system/$(INSTANCE).conf" ]; then \
		echo "❌ Instance not found: $(INSTANCE)"; \
		echo "   Run: make create-instance INSTANCE=$(INSTANCE)"; \
		exit 1; \
	fi
	@echo "📂 Setting permissions for $(INSTANCE)..."
	@# Source the config to get INVENTORY_PATH
	@INVENTORY_PATH=$$(grep INVENTORY_PATH /etc/inventory-system/$(INSTANCE).conf | cut -d= -f2); \
	if [ -z "$$INVENTORY_PATH" ]; then \
		echo "❌ INVENTORY_PATH not set in config"; \
		exit 1; \
	fi; \
	if [ ! -d "$$INVENTORY_PATH" ]; then \
		echo "❌ Directory not found: $$INVENTORY_PATH"; \
		exit 1; \
	fi; \
	echo "   Directory: $$INVENTORY_PATH"; \
	sudo chgrp -R inventory-$(INSTANCE) "$$INVENTORY_PATH"; \
	sudo chmod -R g+rX "$$INVENTORY_PATH"; \
	echo "✅ Permissions set!"

# Start instance
start:
	@echo "🚀 Starting $(INSTANCE)..."
	@sudo systemctl start inventory-web@$(INSTANCE).service
	@sudo systemctl start inventory-api@$(INSTANCE).service
	@echo "✅ $(INSTANCE) started!"
	@$(MAKE) status INSTANCE=$(INSTANCE)

start-web:
	@sudo systemctl start inventory-web@$(INSTANCE).service
	@echo "✅ Web server started for $(INSTANCE)"

start-api:
	@sudo systemctl start inventory-api@$(INSTANCE).service
	@echo "✅ API server started for $(INSTANCE)"

# Stop instance
stop:
	@echo "🛑 Stopping $(INSTANCE)..."
	@sudo systemctl stop inventory-web@$(INSTANCE).service inventory-api@$(INSTANCE).service
	@echo "✅ $(INSTANCE) stopped!"

stop-web:
	@sudo systemctl stop inventory-web@$(INSTANCE).service
	@echo "✅ Web server stopped for $(INSTANCE)"

stop-api:
	@sudo systemctl stop inventory-api@$(INSTANCE).service
	@echo "✅ API server stopped for $(INSTANCE)"

# Restart instance
restart:
	@echo "🔄 Restarting $(INSTANCE)..."
	@sudo systemctl restart inventory-web@$(INSTANCE).service inventory-api@$(INSTANCE).service
	@echo "✅ $(INSTANCE) restarted!"
	@$(MAKE) status INSTANCE=$(INSTANCE)

restart-web:
	@sudo systemctl restart inventory-web@$(INSTANCE).service
	@echo "✅ Web server restarted for $(INSTANCE)"

restart-api:
	@sudo systemctl restart inventory-api@$(INSTANCE).service
	@echo "✅ API server restarted for $(INSTANCE)"

# Status
status:
	@echo "📊 Status for $(INSTANCE):"
	@echo ""
	@echo "Web Server:"
	@sudo systemctl status inventory-web@$(INSTANCE).service --no-pager --lines=0 || true
	@echo ""
	@echo "Chat Server:"
	@sudo systemctl status inventory-api@$(INSTANCE).service --no-pager --lines=0 || true
	@echo ""
	@# Get ports from config
	@if [ -f "/etc/inventory-system/$(INSTANCE).conf" ]; then \
		WEB_PORT=$$(grep WEB_PORT /etc/inventory-system/$(INSTANCE).conf | cut -d= -f2); \
		echo "Access at: http://localhost:$$WEB_PORT/search.html"; \
	fi

# Enable auto-start
enable:
	@sudo systemctl enable inventory-web@$(INSTANCE).service inventory-api@$(INSTANCE).service
	@echo "✅ $(INSTANCE) will auto-start on boot"

# Disable auto-start
disable:
	@sudo systemctl disable inventory-web@$(INSTANCE).service inventory-api@$(INSTANCE).service
	@echo "✅ Auto-start disabled for $(INSTANCE)"

# Logs
logs:
	@echo "📜 Logs for $(INSTANCE) (Ctrl+C to exit)..."
	@sudo journalctl -u inventory-web@$(INSTANCE).service -u inventory-api@$(INSTANCE).service -f

logs-web:
	@echo "📜 Web server logs for $(INSTANCE) (Ctrl+C to exit)..."
	@sudo journalctl -u inventory-web@$(INSTANCE).service -f

logs-api:
	@echo "📜 API server logs for $(INSTANCE) (Ctrl+C to exit)..."
	@sudo journalctl -u inventory-api@$(INSTANCE).service -f

# All instances commands
start-all:
	@for instance in $(INSTANCES); do \
		$(MAKE) start INSTANCE=$$instance; \
	done

stop-all:
	@for instance in $(INSTANCES); do \
		$(MAKE) stop INSTANCE=$$instance; \
	done

restart-all:
	@for instance in $(INSTANCES); do \
		$(MAKE) restart INSTANCE=$$instance; \
	done

enable-all:
	@for instance in $(INSTANCES); do \
		$(MAKE) enable INSTANCE=$$instance; \
	done

status-all:
	@for instance in $(INSTANCES); do \
		echo ""; \
		echo "═══════════════════════════════════════════"; \
		$(MAKE) status INSTANCE=$$instance; \
	done

# List instances
list-instances:
	@echo "📋 Configured instances:"
	@echo ""
	@for conf in /etc/inventory-system/*.conf; do \
		if [ -f "$$conf" ]; then \
			instance=$$(basename $$conf .conf); \
			echo "  $$instance"; \
			WEB_RUNNING=$$(systemctl is-active inventory-web@$$instance.service 2>/dev/null || echo "inactive"); \
			CHAT_RUNNING=$$(systemctl is-active inventory-api@$$instance.service 2>/dev/null || echo "inactive"); \
			echo "    Web:  $$WEB_RUNNING"; \
			echo "    Chat: $$CHAT_RUNNING"; \
		fi; \
	done

# Quick setup
quick-setup:
	@echo "🚀 Quick Setup for Inventory System"
	@echo ""
	@echo "This will:"
	@echo "  1. Install template services"
	@echo "  2. Create furuset and solveig instances"
	@echo ""
	@read -p "Continue? [y/N] " answer; \
	if [ "$$answer" = "y" ]; then \
		$(MAKE) install-templates; \
		$(MAKE) create-instance INSTANCE=furuset; \
		$(MAKE) create-instance INSTANCE=solveig; \
		echo ""; \
		echo "✅ Setup complete!"; \
		echo ""; \
		echo "Next steps:"; \
		echo "  1. Edit configs:"; \
		echo "     sudo nano /etc/inventory-system/furuset.conf"; \
		echo "     sudo nano /etc/inventory-system/solveig.conf"; \
		echo "  2. Set permissions:"; \
		echo "     make set-permissions INSTANCE=furuset"; \
		echo "     make set-permissions INSTANCE=solveig"; \
		echo "  3. Start instances:"; \
		echo "     make start-all"; \
	fi
