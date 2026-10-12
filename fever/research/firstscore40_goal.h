#pragma once
#include "../normal_space.h"
#include "../normal_scoring.h"
#include "../text.h"
#include "../../lib/nlohmann/json.hpp"
#include <chrono>
#include <map>

namespace fever::research::firstscore40 {
using json = nlohmann::json;
struct Observation {
    Field field;
    std::vector<piece::Piece> visible;
    std::string character;
    int t=0, phase=0, since=0, maximum=0, target=0;
};
struct Limits { int transitions=16000, witnesses=48000; double wall_ms=700; };
struct Witness {
    int x=0, color=0, key=0, links=0, points=0, headroom=0;
    Field remaining;
    avec<Field,19> masks;
    std::map<int,int> stages;
};
struct Goal {
    Observation origin;
    Witness base, result;
    std::vector<move::Placement> actions;
    std::vector<Field> after;
    size_t next=0;
    std::string id, kind;
};
// Exposed to native tests: tags annotate the shared pop masks, never drive physics.
void trace_ids(Field origin, Field augmented, Witness& witness);
bool preserves_tail(const Witness& base, const Witness& child, std::string& reason);
json witness_json(const Witness& witness);
json executed_links(avec<Field,19> masks);
class Planner {
    std::optional<Goal> active;
public:
    void reset() { active.reset(); }
    json choose(const Observation& observation, bool goals, Limits limits={});
};
}
