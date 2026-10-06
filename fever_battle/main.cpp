#include "../core/core.h"
#include "../core/fever_queue.h"
#include "../fever/text.h"
#include "../fever/engine.h"
#include "../lib/nlohmann/json.hpp"
#include "search.h"
#include "physics.h"
#include "gauge_wait.h"
#include "color_needs.h"
#include "transition.h"
#include <functional>
#include <stdexcept>
#include <chrono>
#include <bit>
#include <map>

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

// Whether every visible placement loses to the confirmed nuisance, and the
// placements that then end the game before a third drop.
template <class Moves>
json finish_probe(const json& request, Moves& moves, const rule::Rule& rules,
                  const std::function<json(const move::Placement&)>& transition)
{
    const int pending = bounded_integer(request.at("confirmed"), 1, 1000000000, "confirmed");
    const int budget = bounded_integer(request.at("budget_ms"), 0, 1000, "budget_ms");
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(budget);
    std::optional<piece::Piece> next;
    std::optional<piece::Piece> last;
    if (request.contains("next_piece")) {
        next = fever::text::to_piece(request.at("next_piece").get<std::string>());
        if (!next) throw std::invalid_argument("invalid next piece");
    }
    if (request.contains("last_piece")) {
        last = fever::text::to_piece(request.at("last_piece").get<std::string>());
        if (!last) throw std::invalid_argument("invalid last piece");
    }
    const auto surviving_drops = [](Field source, int count) {
        std::vector<Field> result;
        fever_battle::each_remainder_drop(source, count, [&](Field copy) {
            if (!copy.is_dead(rule::FEVER)) result.push_back(copy);
        });
        return result;
    };
    std::map<std::vector<std::string>, bool> last_cache;
    const auto last_has_chance = [&](Field board) -> std::optional<bool> {
        if (!last || pending <= 60) return true;
        auto key = fever::text::from_field(board);
        if (last_cache.contains(key)) return last_cache.at(key);
        auto choices = move::generate(board, *last, rules);
        for (int k = 0; k < choices.get_size(); ++k) {
            if (std::chrono::steady_clock::now() >= deadline) return std::nullopt;
            auto copy = board;
            if (!copy.drop_piece(choices[k].x, choices[k].r, *last, rules))
                throw std::runtime_error("generated last placement failed");
            auto clear = copy.pop();
            if (!copy.is_dead(rule::FEVER) && (clear.get_size() ||
                    !surviving_drops(copy, std::min(30, pending - 60)).empty())) {
                last_cache[key] = true;
                return true;
            }
        }
        last_cache[key] = false;
        return false;
    };
    json candidates = json::array();
    for (int i = 0; i < moves.get_size(); ++i) {
        if (std::chrono::steady_clock::now() >= deadline)
            return {{"proved", false}, {"reason", "budget_inconclusive"}};
        json c = transition(moves[i]);
        if (!c["dead"].get<bool>() && !c["links"].empty())
            return {{"proved", false}, {"reason", "current_clear_can_survive"}};
        int drops = c["dead"].get<bool>() ? 0 : 1;
        if (drops) {
            auto after = read_field(c["field"]);
            for (auto board : surviving_drops(after, std::min(30, pending))) {
                if (!next || pending <= 30)
                    return {{"proved", false}, {"reason", "another_visible_or_unknown_chance"}};
                auto following = move::generate(board, *next, rules);
                for (int j = 0; j < following.get_size(); ++j) {
                    if (std::chrono::steady_clock::now() >= deadline)
                        return {{"proved", false}, {"reason", "budget_inconclusive"}};
                    auto copy = board;
                    if (!copy.drop_piece(following[j].x, following[j].r, *next, rules))
                        throw std::runtime_error("generated next placement failed");
                    auto clear = copy.pop();
                    if (!copy.is_dead(rule::FEVER)) {
                        if (clear.get_size())
                            return {{"proved", false}, {"reason", "next_clear_can_survive"}};
                        for (auto second : surviving_drops(copy, std::min(30, pending - 30))) {
                            auto chance = last_has_chance(second);
                            if (!chance) return {{"proved", false}, {"reason", "budget_inconclusive"}};
                            if (*chance) return {{"proved", false}, {"reason", "last_visible_chance"}};
                            drops = 3;
                        }
                    }
                }
                drops = std::max(drops, 2);
            }
        }
        c["finish_after_drops"] = drops;
        // Proof examines all three visible pieces, but a closing placement
        // must end before a third nuisance drop on every column subset.
        if (drops <= 2) candidates.push_back(c);
    }
    return {{"proved", !candidates.empty()}, {"placements", candidates}};
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
    if (op == "solo") {
        // The chain builder's own request and reply (fever/main.cpp), with its weight set.
        const auto& set = request.at("weights");
        auto reply = fever::answer(request.at("request"), set.get<beam::eval::Weight>(), set);
        if (reply.contains("error")) throw std::invalid_argument(reply["error"].get<std::string>());
        return reply;
    }
    auto field = read_field(request.at("field"));
    if (op == "garbage_search") return fever_battle::search(field, request);
    if (op == "seed_search") return fever_battle::seed_search(field, request);
    if (op == "gauge_wait") return fever_battle::gauge_wait(field, request);
    if (op == "normal_colors") return fever_battle::normal_colors(field, request);
    if (op == "validate") return {{"valid", true}, {"dead", field.is_dead(rule::FEVER)}};
    if (op == "resolve") return resolve(field);
    if (op != "placements" && op != "transition" && op != "finish_probe" && op != "closing_transition") throw std::invalid_argument("unknown operation");
    auto piece = fever::text::to_piece(request.at("piece").get<std::string>());
    if (!piece) throw std::invalid_argument("invalid piece");
    if (field.is_dead(rule::FEVER) && op != "closing_transition") throw std::invalid_argument("already dead field");
    auto rules = rule::FEVER;
    rules.plain_pairs = true;
    if (op == "closing_transition") rules.death_columns = 0;
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
        u8 heights[6];
        field.get_heights(heights);
        const auto geometry = *piece::geometry(*piece, placement.r);
        int contact = 0;
        for (u8 i = 0; i < geometry.count; ++i)
            contact = std::max(contact, int(heights[placement.x + geometry.cells[i].x]) - geometry.cells[i].y);
        result["contact_height"] = contact;
        result["pivot_height"] = contact + geometry.pivot_y;
        result["x"] = placement.x;
        result["r"] = std::string(1, fever::text::from_direction(placement.r));
        result["split"] = drop->split;
        result["discarded"] = drop->discarded;
        return result;
    };
    if (op == "finish_probe") return finish_probe(request, moves, rules, transition);
    if (op == "placements") {
        json results = json::array();
        for (int index = 0; index < moves.get_size(); ++index) results.push_back(transition(moves[index]));
        return {{"placements", results}};
    }
    const auto x = bounded_integer(request.at("x"), 0, 5, "x");
    const auto r = request.at("r").get<std::string>();
    if (r.size() != 1 || std::string("URDL").find(r[0]) == std::string::npos)
        throw std::invalid_argument("r must be U/R/D/L");
    // Only an explicitly observed current pose can request this straight drop.
    // Death reporting still uses FEVER. Ordinary placements retain their BFS.
    if (op == "closing_transition")
        return transition(move::Placement{static_cast<i8>(x), static_cast<direction::Type>(std::string("URDL").find(r[0]))});
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
