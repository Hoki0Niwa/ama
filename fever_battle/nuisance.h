#pragma once
#include "transition.h"

namespace fever_battle {
// Normal nuisance stays held while Fever is active; it never becomes seed nuisance.
// A link offsets the active tray (confirmed then flying), then the held normal tray.
struct EnemyTrays {
    i64 normal_fixed = 0, normal_flying = 0, fever_fixed = 0, fever_flying = 0;
    bool fever = false;
    int enter_at = -1;
    EnemyTrays() = default;
    explicit EnemyTrays(const nlohmann::json& request) {
        const auto destination = request.value("enemy_nuisance_destination", std::string(request.value("enemy_fever", false) ? "fever" : "normal"));
        if (destination != "normal" && destination != "fever")
            throw std::invalid_argument("invalid enemy nuisance destination");
        fever = destination == "fever";
        const auto read = [&](const char* key, const char* legacy, bool active) -> i64 {
            if (request.contains(key)) return number(request, key, 0, 1000000000);
            return active && request.contains(legacy) ? number(request, legacy, 0, 1000000000) : 0;
        };
        normal_fixed = read("enemy_normal_confirmed", "enemy_confirmed", !fever);
        normal_flying = read("enemy_normal_unconfirmed", "enemy_unconfirmed", !fever);
        fever_fixed = read("enemy_fever_confirmed", "enemy_confirmed", fever);
        fever_flying = read("enemy_fever_unconfirmed", "enemy_unconfirmed", fever);
        if (request.contains("enemy_fever_at")) enter_at = number(request, "enemy_fever_at", 0, 1000000);
    }
    void advance(int frame) { if (enter_at >= 0 && frame >= enter_at) fever = true; }
    i64 normal() const { return normal_fixed + normal_flying; }
    i64 seed() const { return fever_fixed + fever_flying; }
    i64 total() const { return normal() + seed(); }
    i64 pending() const { return normal() + (fever ? seed() : 0); }
    i64 offset(i64 amount) {
        const auto take = [&](i64& count) { const i64 n = std::min(count, amount); count -= n; amount -= n; };
        if (fever) { take(fever_fixed); take(fever_flying); }
        take(normal_fixed); take(normal_flying);
        return amount;
    }
    void send(i64 amount, int at) { advance(at); (fever ? fever_flying : normal_flying) += amount; }
    void confirm() { normal_fixed += normal_flying; normal_flying = 0; fever_fixed += fever_flying; fever_flying = 0; }
    nlohmann::json json() const {
        return {{"normal_confirmed", normal_fixed}, {"normal_unconfirmed", normal_flying},
                {"fever_confirmed", fever_fixed}, {"fever_unconfirmed", fever_flying},
                {"destination", fever ? "fever" : "normal"}};
    }
};

template <class Index, class Own>
void advance_enemy(const nlohmann::json& events, const RateSchedule& rates, int until, Index& index,
                   Own& fixed, Own& flying, EnemyTrays& trays, i64& remainder) {
    while (index < Index(events.size()) && events[index]["frame"].template get<int>() <= until) {
        const auto& event = events[index++];
        const int at = event["frame"].template get<int>();
        trays.advance(at);
        if (event["type"] == "end") { fixed += flying; flying = 0; continue; }
        const i64 total = event["points"].template get<i64>() + remainder;
        const int rate = rates.at(at, true);
        i64 amount = total / rate; remainder = total % rate;
        if (trays.pending() && amount == 0) amount = 1;
        flying += Own(trays.offset(amount));
    }
    trays.advance(until);
}
}
