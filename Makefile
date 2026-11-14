# TwinTrace. Works with GNU make; on Windows without make, run the equivalent `python -m src.cli <target>`.
PY ?= python

.PHONY: setup data run test web web-build demo clean

setup:      ## install pinned Python dependencies
	$(PY) -m pip install -r requirements.txt

data:       ## Stage 1: build data/processed/* (background + planted rings + hard negatives + bridge)
	$(PY) -m src.cli data

run:        ## detect, score, evaluate; writes artifacts/ incl. the trained model (about a minute)
	$(PY) -m src.cli run

test:       ## full test-suite
	$(PY) -m pytest -q

web:        ## the interactive investigation board (uses the prebuilt web/dist)
	$(PY) -m src.cli web

web-build:  ## rebuild the front end (needs Node 18+)
	cd web && npm install && npm run build

demo:       ## offline demo from the precomputed artifacts, opens the board
	$(PY) -m src.cli demo

clean:
	rm -rf artifacts data/processed .pytest_cache
