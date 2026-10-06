#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"
namespace fever_battle {
nlohmann::json gauge_wait(Field field, const nlohmann::json& request);
}
