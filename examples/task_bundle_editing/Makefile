# Task Bundle Editing — Makefile
#
# Typical workflow:
#   make task TASK=my_task      set active task (persists in .task)
#   make download               download active task to downloaded_tasks/<task>/
#   make validate               validate the bundle
#   make upload                 upload bundle (auto-generates versioned key)
#   make launch                 launch a job for active task
#
# Config: .env (FLEET_API_KEY) | .task (active task key)

PYTHON       := python3
SCRIPT_DIR   := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
DOWNLOAD     := $(SCRIPT_DIR)download_task.py
UPLOAD       := $(SCRIPT_DIR)upload_task.py
VALIDATE     := $(SCRIPT_DIR)validate_task.py
LAUNCH       := $(SCRIPT_DIR)launch_job.py
TASK_FILE    := .task
BUNDLE_ROOT  := downloaded_tasks

# Read active task from .task file if not set on CLI
ifndef TASK
ifneq (,$(wildcard $(TASK_FILE)))
TASK := $(shell cat $(TASK_FILE))
endif
endif

ifdef TASK
BUNDLE_DIR ?= $(BUNDLE_ROOT)/$(TASK)
endif

# -- Guards --
.env:
	@echo "ERROR: .env not found."
	@echo "  echo 'FLEET_API_KEY=your_key_here' > .env"
	@exit 1

.PHONY: _check-python
_check-python:
	@command -v $(PYTHON) >/dev/null 2>&1 || { \
		echo "ERROR: $(PYTHON) not found on PATH."; \
		echo "  Install Python 3 or set PYTHON= to your interpreter."; \
		exit 1; \
	}

# -- Help --
.PHONY: help
help:
	@echo ""
	@echo "Task Bundle Editing — Makefile"
	@echo "=============================="
	@echo ""
	@echo "  make task TASK=<key>       Set active task (saved to .task)"
	@echo "  make download              Download active task       [TASK= OUT=]"
	@echo "  make upload                Upload bundle, no job      [DIR= KEY= VERSION=]"
	@echo "  make launch                Launch job for active task [KEY= MODELS= PASS_K=]"
	@echo "  make validate              Validate bundle            [DIR= KEY=]"
	@echo ""
	@echo "  make clean                 Clear active task key (.task)"
	@echo "  make clean-all             Remove active task bundle + clear task key"
	@echo ""
	@echo "  make env                   Show current environment + active task"
	@echo ""
	@echo "Bundles download to: $(BUNDLE_ROOT)/<task>/"
	@echo "Config: .env (FLEET_API_KEY) | .task (active task key)"

.DEFAULT_GOAL := help

# -- Set active task --
.PHONY: task
task:
ifndef TASK
	$(error TASK is required. Usage: make task TASK=my_task)
endif
	@echo "$(TASK)" > $(TASK_FILE)
	@echo "Active task: $(TASK)"
	@if [ -d "$(BUNDLE_ROOT)/$(TASK)" ]; then \
		echo "Bundle dir:  $(BUNDLE_ROOT)/$(TASK)/"; \
	else \
		echo "Bundle dir:  (not found — run make download or set DIR= for upload/validate)"; \
	fi

# -- Download --
.PHONY: download
download: .env _check-python
ifndef TASK
	$(error No active task. Run: make task TASK=my_task)
endif
	$(PYTHON) $(DOWNLOAD) \
		--task-key $(TASK) \
		--output-dir $(or $(OUT),$(BUNDLE_DIR))

# -- Upload --
.PHONY: upload
upload: .env _check-python
ifndef DIR
ifndef TASK
	$(error No active task or DIR. Run: make task TASK=my_task, or pass DIR=)
endif
endif
	$(PYTHON) $(UPLOAD) \
		--dir $(or $(DIR),$(BUNDLE_DIR)) \
		$(if $(KEY),--key $(KEY)) \
		$(if $(VERSION),--env-version $(VERSION)) \
		--no-launch-job

# -- Launch job --
.PHONY: launch
launch: .env _check-python
ifndef TASK
	$(error No active task. Run: make task TASK=my_task)
endif
	$(PYTHON) $(LAUNCH) \
		--task-key $(or $(KEY),$(TASK)) \
		$(if $(MODELS),--models $(MODELS)) \
		$(if $(PASS_K),--pass-k $(PASS_K))

# -- Validate --
.PHONY: validate
validate: _check-python
ifndef DIR
ifndef TASK
	$(error No active task or DIR. Run: make task TASK=my_task, or pass DIR=)
endif
endif
	$(PYTHON) $(VALIDATE) \
		$(or $(DIR),$(BUNDLE_DIR)) \
		$(if $(KEY),--new-key $(KEY))

# -- Clean --
.PHONY: clean
clean:
	@if [ -f $(TASK_FILE) ]; then \
		echo "Cleared active task: $$(cat $(TASK_FILE))"; \
		rm -f $(TASK_FILE); \
	else \
		echo "No active task to clear"; \
	fi

.PHONY: clean-all
clean-all:
ifndef TASK
	$(error No active task to clean. Run: make task TASK=my_task)
endif
	@if [ -d "$(BUNDLE_DIR)" ]; then \
		echo "Removing $(BUNDLE_DIR)/"; \
		rm -rf "$(BUNDLE_DIR)"; \
	else \
		echo "Nothing to clean: $(BUNDLE_DIR)/ does not exist"; \
	fi
	@rm -f $(TASK_FILE)
	@echo "Cleared active task"

# -- Environment info --
.PHONY: env
env: .env
	@echo ""
	@key_tail="$$(grep '^FLEET_API_KEY=' .env | cut -d= -f2 | tail -c 9)"; \
	if [ -n "$$key_tail" ]; then \
		echo "FLEET_API_KEY : ********$$key_tail"; \
	else \
		echo "FLEET_API_KEY : (not set)"; \
	fi
	@url="$$(grep '^FLEET_BASE_URL=' .env | cut -d= -f2-)"; \
	if [ -n "$$url" ]; then \
		echo "FLEET_BASE_URL: $$url"; \
	else \
		echo "FLEET_BASE_URL: (default: https://orchestrator.fleetai.com)"; \
	fi
	@if [ -f $(TASK_FILE) ]; then \
		task_key="$$(cat $(TASK_FILE))"; \
		echo "Active task   : $$task_key"; \
		if [ -d "$(BUNDLE_ROOT)/$$task_key" ]; then \
			echo "Bundle dir    : $(BUNDLE_ROOT)/$$task_key/"; \
		else \
			echo "Bundle dir    : (not found)"; \
		fi; \
	else \
		echo "Active task   : (none — run: make task TASK=my_task)"; \
	fi
	@echo ""
