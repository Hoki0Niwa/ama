#pragma once
#include <algorithm>

namespace fever_battle::disruption {
// End our attack with the opponent's entry/seed turnover, or within one
// ordinary Fever placement after it. An unknown turnover is not a target.
constexpr int WINDOW = 26;
inline bool timed(int attack_end, int seed_at, int window = WINDOW) {
    return seed_at >= 0 && attack_end >= seed_at && attack_end <= seed_at + window;
}
struct Rating { double value = 0; const char* kind = "none"; };
inline Rating extension(long long extra, bool allowed, bool checked, bool regular_after_drop, bool skip) {
    if (!allowed || !checked || regular_after_drop || skip || extra < 6) return {};
    return {std::clamp(double(extra)/12.0,0.0,1.0), "extension_pressure"};
}
// A forecast of retained nuisance, not proof that it actually hit an ignition.
// One or two nuisance must not buy the same reward as two rows. A main may
// be spent for a jab on a small board, or for pressure surviving the next seed.
inline Rating rate(long long residual, long long baseline, long long reply,
                   bool at_turnover, bool jab_allowed, bool skip_jab, bool main, bool current_attack = false,
                   bool allow_main_pressure = true) {
    const auto extra = std::max(0LL, residual - baseline);
    if (!extra || baseline >= reply + 6) return {};
    if ((!main || allow_main_pressure) && residual >= reply + 6 && extra >= 6)
        return {1.0 + std::clamp(double(residual - reply) / 30.0, 0.0, 2.0),
                main ? "main_pressure" : "overpower"};
    // A resource-preserving shot can beat the *current* observed attack
    // without also beating the following seed. A full main is held to the
    // stronger persistent-pressure test above.
    if (!main && current_attack && extra >= 12)
        return {1.0 + std::clamp(double(extra) / 30.0, 0.0, 1.0), "overpower"};
    if (at_turnover && jab_allowed && !skip_jab)
        return {std::clamp(double(extra) / 12.0, 0.0, 1.0), "jab"};
    return {};
}
}
