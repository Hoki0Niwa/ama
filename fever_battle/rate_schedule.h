#pragma once
#include "../lib/nlohmann/json.hpp"
#include <stdexcept>
#include <vector>

namespace fever_battle {
// Boundaries apply to score conversion at each pop, including carried points.
// Separate observation bounds avoid overestimating our attack or understating
// the opponent's when a rate change was observed between two captures.
class RateSchedule {
    using json = nlohmann::json;
    int initial;
    std::vector<std::pair<int,int>> own, enemy;
    static auto parse(const json& events) {
        std::vector<std::pair<int,int>> result;
        if (!events.is_array()) throw std::invalid_argument("rate events must be an array");
        int previous = -1;
        for (const auto& event : events) {
            const auto& frame = event.at("frame"); const auto& rate = event.at("target_point");
            if (!frame.is_number_integer() || frame < 0 || frame > 1000000 || frame <= previous ||
                !rate.is_number_integer() || rate < 1 || rate > 100000)
                throw std::invalid_argument("invalid rate event");
            previous = frame.get<int>();
            result.emplace_back(previous, rate.get<int>());
        }
        return result;
    }
public:
    RateSchedule(const json& request, int rate): initial(rate),
        own(parse(request.value("rate_events", json::array()))),
        enemy(parse(request.value("enemy_rate_events", request.value("rate_events", json::array())))) {}
    int at(int frame, bool opponent = false) const {
        int rate = initial;
        for (const auto& [boundary, value] : opponent ? enemy : own) {
            if (boundary > frame) break;
            rate = value;
        }
        return rate;
    }
};
}
