LEVEL ?= 1
COMPOSE ?= docker compose
PYTHON ?= python3
PUBLIC_URL ?= http://localhost

files_1 := -f compose.yaml
files_2 := $(files_1) -f compose.cache.yaml
files_3 := $(files_2) -f compose.secure.yaml
files_4 := $(files_3) -f compose.auth.yaml
files := $(files_$(LEVEL))

ifeq ($(files),)
$(error LEVEL must be 1, 2, 3, or 4)
endif

.PHONY: up pull config smoke logs down refresh grants reset
up:
	$(COMPOSE) $(files) up -d --build --wait

pull:
	$(COMPOSE) $(files) pull
	$(COMPOSE) $(files) up -d --no-build --wait

config:
	$(COMPOSE) $(files) config --quiet

smoke:
ifeq ($(LEVEL),4)
	$(PYTHON) tests/oidc_deployment.py
else
	$(PYTHON) scripts/smoke_test.py --url "$(PUBLIC_URL)" --level "$(LEVEL)"
endif

logs:
	$(COMPOSE) $(files) logs --tail=100 -f

down:
	$(COMPOSE) $(files) down

refresh:
	$(PYTHON) scripts/refresh.py $(files)

grants:
	$(COMPOSE) $(files) run --rm --no-deps -e GEOREST_ADMIN_DSN configure grants

reset:
	@printf 'Delete this project’s database and configuration volumes? [y/N] '; \
	read -r answer; \
	case "$$answer" in y|Y|yes|YES) $(COMPOSE) $(files) down --volumes;; esac
