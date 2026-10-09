#include "color_needs.h"
#include "../fever/text.h"
#include "transition.h"
#include <bit>
#include <tuple>

namespace fever_battle {
using json = nlohmann::json;
namespace {
std::array<int,4> available(const std::vector<piece::Piece>& queue, size_t start) {
    std::array<int,4> counts{};
    for (size_t i = start; i < queue.size(); ++i) {
        // Big puyos can choose any one of the four colors. This is supply
        // for a single trigger, not four simultaneous bundles of four cells.
        if (queue[i].shape == piece::Shape::BIG) {
            for (auto& n : counts) n += 4;
        } else for (size_t k = 0; k < piece::cell_count(queue[i].shape); ++k)
            ++counts[int(queue[i].colors[k])];
    }
    return counts;
}
std::vector<piece::Piece> pieces(const json& request) {
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("visible queue only");
    std::vector<piece::Piece> result;
    for (const auto& text : queue) {
        auto p = fever::text::to_piece(text);
        if (!p) throw std::invalid_argument("invalid visible piece");
        result.push_back(*p);
    }
    return result;
}
}
ColorNeeds color_needs(Field field) {
    ColorNeeds result;
    auto rules = rule::FEVER; rules.plain_pairs = true; rules.special_moves = true;
    if (field.is_dead(rules)) return result;
    for (int c = 0; c < 4; ++c) {
        if (field.data[c].is_empty()) continue;
        auto color = static_cast<cell::Type>(c);
        auto moves = move::generate(field, piece::from_pair({color, color}), rules);
        for (int i = 0; i < moves.get_size(); ++i) {
            if (moves[i].r != direction::Type::UP) continue;
            int x = moves[i].x, y = field.get_height(x);
            auto probe = field;
            for (int n = 1; n <= 3 && y + n <= 13; ++n) {
                probe.set_cell(x, y + n - 1, color);
                auto resolved = probe;
                int chain = resolved.pop_count();
                if (!chain) continue;
                result.chain = std::max(result.chain, chain);
                result.ports.push_back({c, x, y, n, chain});
                break;
            }
        }
    }
    for (const auto& port : result.ports)
        if (result.chain >= 2 && port.chain == result.chain)
            result.reserve[port.color] = std::max(result.reserve[port.color], result.chain - 1);
    return result;
}
int ColorNeeds::quality(const std::vector<piece::Piece>& queue, size_t start) const {
    auto supply = available(queue, start);
    int value = 0;
    for (const auto& p : ports)
        value = std::max(value, p.chain * 400 - std::max(0, p.needed - supply[p.color]) * 100 - p.needed * 20);
    return value;
}
json ColorNeeds::describe(const std::vector<piece::Piece>& queue, size_t start) const {
    auto supply = available(queue, start);
    json mainline = json::array(), offsets = json::array(), weights = json::object();
    for (int c = 0; c < 4; ++c) weights[std::string(1, cell::to_char(static_cast<cell::Type>(c)))] = reserve[c];
    for (const auto& p : ports) {
        json port = {{"color", std::string(1, cell::to_char(static_cast<cell::Type>(p.color)))},
            {"x", p.x}, {"height", p.y}, {"needed_cells", p.needed}, {"chain", p.chain},
            {"visible_supply", supply[p.color]}, {"missing_visible_cells", std::max(0, p.needed-supply[p.color])}};
        if (p.chain == chain) mainline.push_back(port);
        if (p.chain <= 2) offsets.push_back(port);
    }
    return {{"mainline_chain", chain}, {"mainline", mainline}, {"offsets", offsets},
        {"reserve_weights", weights}, {"quality", quality(queue, start)},
        {"status", "reachable_color_completion_heuristic_not_executable_future"},
        {"supply_status", "visible_color_counts_shape_and_placement_not_guaranteed"}};
}
json normal_colors(Field field, const json& request) {
    auto queue = pieces(request);
    auto root = color_needs(field);
    json candidates = json::array();
    const auto& pending = request.at("confirmed");
    if (!pending.is_number_integer() || pending < 0 || pending > 1000000000)
        throw std::invalid_argument("invalid confirmed nuisance");
    int fixed = pending.get<int>();
    auto rules = rule::FEVER; rules.plain_pairs = true; rules.special_moves = true;
    auto moves = move::generate(field, queue[0], rules);
    for (int i = 0; i < moves.get_size(); ++i) {
        auto child = field;
        if (!child.drop_piece(moves[i].x, moves[i].r, queue[0], rules)) continue;
        auto masks = child.pop(); int loss = 0, popped = 0;
        for (int k = 0; k < masks.get_size(); ++k) for (int c = 0; c < 4; ++c) {
            int n = masks[k].data[c].get_count(); popped += n; loss += n * root.reserve[c];
        }
        int dropped = masks.get_size() ? 0 : std::min(30, fixed);
        bool alive = !child.is_dead(rules);
        int worst_quality = 1000000, worst_chain = 100;
        each_remainder_drop(child, dropped, [&](Field board) {
            alive &= !board.is_dead(rules);
            auto needs = color_needs(board);
            worst_quality = std::min(worst_quality, needs.quality(queue, 1));
            worst_chain = std::min(worst_chain, needs.chain);
        });
        candidates.push_back({{"x", moves[i].x}, {"r", std::string(1, fever::text::from_direction(moves[i].r))},
            {"survives", alive}, {"chain", masks.get_size()}, {"popped", popped},
            {"needed_color_consumed", loss}, {"remaining_chain", worst_chain},
            {"remaining_color_quality", worst_quality}, {"dropped", dropped}});
    }
    return {{"needs", root.describe(queue, 0)}, {"candidates", candidates},
        {"nuisance_policy", "all_remainder_subsets_confirmed_only"}};
}
}
