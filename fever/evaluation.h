#pragma once
#include "search.h"

namespace fever {
struct Potential {
    int chain = 0, score = 0, key = 0;
    i32 value = 0;
    int near_chain = 0; // Longest trigger needing at most two puyos, independent of shape weights
};

// Cheap single-column extension remains a potential estimate, never a firing promise.
Potential potential(Field field, const beam::eval::Weight& w, const Configs& configs);
}
