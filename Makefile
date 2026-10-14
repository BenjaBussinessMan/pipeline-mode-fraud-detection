.PHONY: up simulate down logs test docker-test

up:
	docker compose up --build -d

simulate:
	docker compose --profile sim up -d producer

down:
	docker compose --profile sim down -v

logs:
	docker compose logs -f consumer

test:
	pytest

docker-test:
	docker build --target test .
