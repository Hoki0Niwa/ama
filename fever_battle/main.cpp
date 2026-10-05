#include "../core/core.h"
#include "../core/fever_queue.h"
#include "../fever/text.h"
#include "../lib/nlohmann/json.hpp"
#include "search.h"
#include "physics.h"
#include <stdexcept>

using json = nlohmann::json;

// Separate normal-battle worker. Shared evaluation is read-only; the stage-A
// engine and Tsu engine remain independent processes and binaries.
namespace {
int bounded_integer(const json& value, int low, int high, const char* name)
{
    if (!value.is_number_integer() || value < low || value > high)
        throw std::invalid_argument(std::string(name) + " must be an integer in range");
    return value.get<int>();
}

Field read_field(const json& input)
{
    const auto rows = input.get<std::vector<std::string>>();
    if (rows.size() != 14 || rows[0] != "......")
        throw std::invalid_argument("field must have an empty 14th row");
    for (const auto& row : rows) {
        if (row.size() != 6 || row.find_first_not_of("RYGB#.") != std::string::npos)
            throw std::invalid_argument("field must have 14 rows of six RYGB#. cells");
    }
    auto field = fever::text::to_field(rows);
    if (!field) throw std::invalid_argument("floating cells in settled field");
    return *field;
}

json resolve(Field field)
{
    auto initial = field;
    auto masks = field.pop();
    auto distances = fever_battle::fall_distances(initial, masks);
    auto features = fever_battle::fall_features(initial, masks);
    json links = json::array();
    for (int index = 0; index < masks.get_size(); ++index) {
        auto mask = masks[index];
        json groups = json::array();
        int colors = 0;
        for (int c = 0; c < cell::COUNT - 1; ++c) {
            if (mask.data[c].is_empty()) continue;
            ++colors;
            while (!mask.data[c].is_empty()) {
                auto group = mask.data[c].get_mask_group_lsb();
                groups.push_back(group.get_count());
                mask.data[c] = mask.data[c] & ~group;
            }
        }
        links.push_back({{"groups", groups}, {"colors", colors}});
    }
    return {{"field", fever::text::from_field(field)}, {"links", links},
            {"fall_distances", distances},
            {"fall_features", features},
            {"dead", field.is_dead(rule::FEVER)}, {"all_clear", field.is_empty()}};
}

json answer(const json& request)
{
    const auto op = request.at("op").get<std::string>();
    if (op == "queue") {
        const auto count = bounded_integer(request.at("count"), 1, 10000, "count");
        const auto seed = request.at("seed");
        if (!seed.is_number_unsigned() && (!seed.is_number_integer() || seed.get<i64>() < 0))
            throw std::invalid_argument("seed must be a nonnegative integer");
        auto queue = fever::create_queue(request.at("character").get<std::string>(), seed.get<u64>(), count);
        if (!queue) throw std::invalid_argument("unknown character or dropset");
        json values = json::array();
        for (usize index = 0; index < queue->size(); ++index) {
            auto text = fever::text::from_piece((*queue)[index]);
            const auto* character = dropset::find(request.at("character").get<std::string>());
            // Equal-color horizontal triples still occupy a J slot of the cycle.
            text[0] = character->pattern[index % dropset::PERIOD];
            values.push_back(text);
        }
        return {{"queue", values}, {"color_model", "prototype_splitmix4"}};
    }
    auto field = read_field(request.at("field"));
    if (op == "garbage_search") return fever_battle::search(field, request);
    if (op == "seed_search") return fever_battle::seed_search(field, request);
    if (op == "validate") return {{"valid", true}, {"dead", field.is_dead(rule::FEVER)}};
    if (op == "resolve") return resolve(field);
    if (op != "placements" && op != "transition") throw std::invalid_argument("unknown operation");
    auto piece = fever::text::to_piece(request.at("piece").get<std::string>());
    if (!piece) throw std::invalid_argument("invalid piece");
    if (field.is_dead(rule::FEVER)) throw std::invalid_argument("already dead field");
    auto rules = rule::FEVER;
    rules.plain_pairs = true;
    auto moves = move::generate(field, *piece, rules);
    const auto transition = [&](const move::Placement& placement) {
        auto copy = field;
        const auto drop = copy.drop_piece(placement.x, placement.r, *piece, rules);
        if (!drop) throw std::runtime_error("generated placement failed");
        auto locked = fever::text::from_field(copy);
        auto split_distances = fever_battle::split_distances(field, *piece, placement.x, placement.r);
        auto result = resolve(copy);
        result["locked_field"] = locked;
        result["split_distances"] = split_distances;
        result["x"] = placement.x;
        result["r"] = std::string(1, fever::text::from_direction(placement.r));
        result["split"] = drop->split;
        result["discarded"] = drop->discarded;
        return result;
    };
    if (op == "placements") {
        json results = json::array();
        for (int index = 0; index < moves.get_size(); ++index) results.push_back(transition(moves[index]));
        return {{"placements", results}};
    }
    const auto x = bounded_integer(request.at("x"), 0, 5, "x");
    const auto r = request.at("r").get<std::string>();
    if (r.size() != 1 || std::string("URDL").find(r[0]) == std::string::npos)
        throw std::invalid_argument("r must be U/R/D/L");
    for (int index = 0; index < moves.get_size(); ++index)
        if (moves[index].x == x && fever::text::from_direction(moves[index].r) == r[0]) return transition(moves[index]);
    throw std::invalid_argument("placement is unreachable by the conservative route model");
}
}

int main()
{
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        try { std::cout << answer(json::parse(line)).dump() << std::endl; }
        catch (const std::exception& e) { std::cout << json{{"error", e.what()}}.dump() << std::endl; }
    }
}
