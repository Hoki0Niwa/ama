CXX = g++

ifeq ($(PROF), true)
CXXPROF += -pg -no-pie
else
CXXPROF += -s
endif

ifeq ($(BUILD), debug)
CXXFLAGS += -fdiagnostics-color=always -DUNICODE -std=c++20 -Wall -Og -pg -no-pie
else
CXXFLAGS += -DUNICODE -DNDEBUG -std=c++20 -O3 -msse4.1 -flto $(CXXPROF)
endif

ifeq ($(PEXT), true)
CXXFLAGS += -DPEXT -mbmi2
endif

# The default selects BMI2 at runtime; NATIVE=true opts into a CPU-specific build.
ifeq ($(NATIVE), true)
CXXFLAGS += -march=native
endif

SRC_AI = core/*.cpp ai/*.cpp ai/search/*.cpp ai/search/beam/*.cpp ai/search/dfs/*.cpp

# Fever targets (this branch only), the same sources as build.ps1: the fever engine's search and
# builder without its main are shared by its bench and by the battle worker. BIN moves their output.
SRC_FEVER = $(filter-out fever/main.cpp,$(wildcard fever/*.cpp))
BIN ?= bin

.PHONY: all puyop test tuner bench pvp fever bench_fever fever_battle clean makedir

all: puyop

puyop: makedir
	@$(CXX) $(CXXFLAGS) $(SRC_AI) puyop/*.cpp -o bin/puyop/puyop.exe

tuner: makedir
	@$(CXX) $(CXXFLAGS) $(SRC_AI) tuner/*.cpp -o bin/tuner/tuner.exe

test: makedir
	@$(CXX) $(CXXFLAGS) $(SRC_AI) test/*.cpp -o bin/test/test.exe

bench: makedir
	@$(CXX) $(CXXFLAGS) $(SRC_AI) bench/*.cpp -o bin/bench/bench.exe

pvp: makedir
	@$(CXX) $(CXXFLAGS) $(SRC_AI) pvp/*.cpp -o bin/pvp/pvp.exe

fever:
	@mkdir -p $(BIN)/fever
	@$(CXX) $(CXXFLAGS) $(SRC_AI) fever/*.cpp -o $(BIN)/fever/fever.exe

bench_fever:
	@mkdir -p $(BIN)/bench_fever
	@$(CXX) $(CXXFLAGS) $(SRC_AI) $(SRC_FEVER) bench_fever/*.cpp -o $(BIN)/bench_fever/bench_fever.exe

fever_battle:
	@mkdir -p $(BIN)/fever_battle
	@$(CXX) $(CXXFLAGS) $(SRC_AI) $(SRC_FEVER) fever_battle/*.cpp -o $(BIN)/fever_battle/fever_battle.exe

clean: makedir
	@rm -rf bin
	@make makedir

makedir:
	@mkdir -p bin
	@mkdir -p bin/puyop
	@mkdir -p bin/test
	@mkdir -p bin/tuner/data
	@mkdir -p bin/bench
	@mkdir -p bin/pvp

.DEFAULT_GOAL := puyop
