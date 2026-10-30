#pragma once
#include "physics.h"

namespace fever_battle {
struct AttackTimes { int lock = 0, end = 0, ready = 0; };
// Same placement/split and link clock used by tactics.cpp. End confirms a packet;
// this is the model's send time, not a measured flight/landing guarantee.
inline AttackTimes attack_times(Field locked, avec<Field,19>& masks, int split_rows,
                                int ready, const nlohmann::json& timing, int pace = 0) {
    AttackTimes out;
    const auto& table = timing.at("split_extra_frames");
    const int extra = table[split_rows].is_null() ? split_rows * timing.at("fall_frames_per_row").get<int>()
                                                : table[split_rows].get<int>();
    out.lock = ready + std::max(timing.at("placement_frames").get<int>(),
                              pace - timing.at("spawn_frames").get<int>()) + extra;
    out.end = out.lock;
    if (masks.get_size()) {
        const auto features = fall_features(locked, masks);
        const auto falls = fall_distances(locked, masks);
        out.end += timing.value("first_link_frames", 0);
        for (int i = 0; i < masks.get_size(); ++i)
            out.end += timing.value("geometry_timing", false)
                ? link_frames(features[i], i == masks.get_size()-1,
                              timing.at("pop_frames").get<int>(), timing.at("settle_frames").get<int>())
                : timing.at("pop_frames").get<int>() + timing.at("settle_frames").get<int>()
                    + falls[i] * timing.at("fall_frames_per_row").get<int>();
        out.ready = out.end + timing.value("chain_ready_frames", 0);
    } else out.ready = std::max(out.lock + timing.at("spawn_frames").get<int>(), ready + pace);
    return out;
}
}
