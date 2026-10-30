#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
inline int followup_gauge_limit(int frames, int step = 120) {
    return std::max(0, 3 - std::max(0, frames - 1) / step);
}
nlohmann::json normal_followup(Field field, const nlohmann::json& request);
}
