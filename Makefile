PY ?= python3

.PHONY: all ingest build dq site test clean

all: build dq site test

ingest:
	$(PY) pipeline/ingest.py

build:
	$(PY) pipeline/build.py

dq: build
	$(PY) pipeline/dq.py

site:
	$(PY) pipeline/site.py

test: dq
	$(PY) -m unittest discover -s tests

clean:
	rm -rf data/staging data/warehouse data/marts site/index.html
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
