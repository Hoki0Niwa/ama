#pragma once
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
// One column of a link: its longest fall and the puyos stacked above the first.
inline int column_contact_frames(int distance, int above) {
    return 2*distance-1+(above ? (3*above+1)/2+1 : 0);
}
// Distances are ordered bottom-to-top within each column, including holes
// created by adjacent garbage. Columns fall concurrently; stacks collide.
inline int contact_frames(const nlohmann::json& feature) {
    int result=0;
    for (const auto& column : feature.at("moving_distances_by_column")) {
        if (column.empty()) continue;
        int distance=0;
        for (const auto& value : column) distance=std::max(distance,value.get<int>());
        result=std::max(result,column_contact_frames(distance,int(column.size())-1));
    }
    return result;
}
inline int link_frames(int fall, bool terminal, int pop=55, int settle=14) {
    return terminal && !fall ? pop : pop+settle+fall;
}
inline int link_frames(const nlohmann::json& feature, bool terminal, int pop=55, int settle=14) {
    return link_frames(contact_frames(feature), terminal, pop, settle);
}
}
