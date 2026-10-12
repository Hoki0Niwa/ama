#pragma once
#include "fire.h"

namespace fever {
// Normal-board space and visible extension only; no invented colors or attacks.
json inspect_capacity(Field field, const Queue& queue, const rule::Rule& rules,
                      const normal_scoring::Entry* normal, int target = 14, bool threat = false);
}
