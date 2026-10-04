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

.PHONY: all puyop test tuner bench pvp clean makedir

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
