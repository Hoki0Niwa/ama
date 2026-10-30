#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
// Quiet normal boards only. The firing path is known; recovery uses virtual bags.
nlohmann::json normal_conversion(Field field, const nlohmann::json& request);
}
