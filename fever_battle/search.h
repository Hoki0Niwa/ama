#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
nlohmann::json search(Field field, const nlohmann::json& request);
nlohmann::json seed_search(Field field, const nlohmann::json& request);
nlohmann::json seed_defense(Field field, const nlohmann::json& request);
}
