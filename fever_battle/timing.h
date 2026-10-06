#pragma once
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
// Distances are ordered bottom-to-top within each column, including holes
// created by adjacent garbage. Columns fall concurrently; stacks collide.
inline int contact_frames(const nlohmann::json& feature) {
    int result=0;
    for (const auto& column : feature.at("moving_distances_by_column")) {
        if (column.empty()) continue;
        int distance=0;
        for (const auto& value : column) distance=std::max(distance,value.get<int>());
        const int above=int(column.size())-1;
        result=std::max(result,2*distance-1+(above ? (3*above+1)/2+1 : 0));
    }
    return result;
}
inline int link_frames(const nlohmann::json& feature, bool terminal, int pop=55, int settle=14) {
    const int fall=contact_frames(feature);
    return terminal && !fall ? pop : pop+settle+fall;
}
}
