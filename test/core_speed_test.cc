#include "../core/core.h"
#include "../ai/search/beam/quiet.h"
#include "../ai/search/beam/eval.h"
#include "../ai/search/beam/table.h"
#include <random>
#include <stdexcept>
#include <type_traits>

static void check(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

// Independent scalar model: flood-fill only rows 1-12, remove adjacent garbage,
// then apply gravity through row 13. Row 14 follows Field's separate occupancy.
static i32 scalar_pop(Field& field)
{
    cell::Type grid[13][6];
    for (i32 y = 0; y < 13; ++y)
        for (i32 x = 0; x < 6; ++x) grid[y][x] = field.get_cell(x, y);
    i32 count = 0;
    for (; count < 19; ++count) {
        bool visited[12][6] = {};
        bool erase[13][6] = {};
        bool any = false;
        for (i32 y = 0; y < 12; ++y) {
            for (i32 x = 0; x < 6; ++x) {
                auto color = grid[y][x];
                if (visited[y][x] || color == cell::Type::NONE || color == cell::Type::GARBAGE) continue;
                std::vector<std::pair<i32, i32>> group = {{x, y}};
                visited[y][x] = true;
                for (size_t i = 0; i < group.size(); ++i) {
                    auto [gx, gy] = group[i];
                    for (auto [dx, dy] : {std::pair{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
                        i32 nx = gx + dx, ny = gy + dy;
                        if (nx < 0 || nx >= 6 || ny < 0 || ny >= 12 || visited[ny][nx] || grid[ny][nx] != color) continue;
                        visited[ny][nx] = true;
                        group.emplace_back(nx, ny);
                    }
                }
                if (group.size() < 4) continue;
                any = true;
                for (auto [gx, gy] : group) {
                    erase[gy][gx] = true;
                    for (auto [dx, dy] : {std::pair{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
                        i32 nx = gx + dx, ny = gy + dy;
                        if (nx >= 0 && nx < 6 && ny >= 0 && ny < 13 && grid[ny][nx] == cell::Type::GARBAGE)
                            erase[ny][nx] = true;
                    }
                }
            }
        }
        if (!any) break;
        for (i32 x = 0; x < 6; ++x) {
            i32 destination = 0;
            // The field represents cells by bits, including gaps. Erasing a row
            // shifts every bit above it, without collapsing unrelated gaps.
            for (i32 y = 0; y < 13; ++y) {
                if (!erase[y][x]) grid[destination++][x] = grid[y][x];
            }
            while (destination < 13) grid[destination++][x] = cell::Type::NONE;
        }
    }
    auto row14 = field.row14;
    field = Field();
    field.row14 = row14;
    for (i32 y = 0; y < 13; ++y)
        for (i32 x = 0; x < 6; ++x)
            if (grid[y][x] != cell::Type::NONE) field.set_cell(x, y, grid[y][x]);
    return count;
}

int main()
{
    try {
        static_assert(!std::is_copy_constructible_v<Table>);
        static_assert(std::is_nothrow_move_constructible_v<Table>);
        Table table;
        table.resize(1);
        const u64 hash = 0x8765432100011234ULL;
        auto [found, entry] = table.get(hash);
        check(!found, "fresh table");
        table.set(entry, hash, 17, 31);
        Table moved(std::move(table));
        check(moved.get(hash).first && moved.get(hash).second->eval == 31, "moved table retains data");
        Table assigned;
        assigned.resize(1);
        assigned = std::move(moved);
        check(assigned.get(hash).first && assigned.get(hash).second->action == 17, "move assignment retains data");
        table.resize(1);
        check(!table.get(hash).first, "moved-from table can resize");

        std::mt19937 rng(20261004);
        i32 quiet_results = 0;
        for (i32 trial = 0; trial < 2000; ++trial) {
            Field original;
            for (i8 x = 0; x < 6; ++x) {
                i32 height = rng() % 14;
                for (i8 y = 0; y < height; ++y) {
                    if (trial % 3 == 0 && rng() % 5 == 0) continue;
                    original.set_cell(x, y, cell::Type(rng() % cell::COUNT));
                }
            }
            original.row14 = rng() & 63;
            auto scalar = original, full = original, counted = original;
            i32 expected = scalar_pop(scalar);
            auto masks = full.pop();
            check(masks.get_size() == expected, "recorded chain length matches scalar rules");
            check(full == scalar, "recorded final field matches scalar rules");
            check(counted.pop_count() == expected, "count-only chain length matches scalar rules");
            check(counted == scalar, "count-only final field matches scalar rules");
            check(full.row14 == original.row14, "row 14 occupancy preserved");
            if (trial < 500) {
                std::vector<beam::quiet::Result> scored, lengths;
                beam::quiet::search(original, 3, [&](auto result) { scored.push_back(result); });
                beam::quiet::search_count(original, 3, [&](auto result) { lengths.push_back(result); });
                check(scored.size() == lengths.size(), "quiet candidate count");
                for (size_t i = 0; i < scored.size(); ++i) {
                    check(scored[i].chain.count == lengths[i].chain.count && scored[i].x == lengths[i].x &&
                          scored[i].key == lengths[i].key && scored[i].remain == lengths[i].remain,
                          "quiet candidate order and evaluated inputs are identical");
                    check(lengths[i].chain.score == 0, "count-only path omits point score");
                    bool reconstructed = false;
                    for (u8 color = 0; color < cell::COUNT - 1; ++color) {
                        auto candidate = original;
                        u8 heights[6];
                        candidate.get_heights(heights);
                        for (i32 added = 0; added < scored[i].key; ++added)
                            candidate.data[color].set_bit(scored[i].x, heights[scored[i].x] + added);
                        auto links = candidate.pop();
                        if (links.get_size() != scored[i].chain.count || !(candidate == scored[i].remain)) continue;
                        bool sizes_match = true;
                        for (i32 link = 0; link < links.get_size(); ++link)
                            sizes_match &= scored[i].popped[link] == links[link].get_count();
                        auto points = chain::get_score(links);
                        reconstructed |= sizes_match && points.score == scored[i].chain.score;
                    }
                    check(reconstructed, "quiet preserves link sizes before score consumes masks");
                }
                for (i32 score_weight : {0, 1000}) {
                    beam::eval::Weight weight;
                    weight.chain = 100;
                    weight.score = score_weight;
                    i32 expected_eval = INT32_MIN;
                    for (const auto& result : scored) {
                        i32 value = result.chain.count * weight.chain;
                        if (score_weight != 0) {
                            i32 pure = 40;
                            for (i32 link = 1; link < result.chain.count; ++link)
                                pure += 40 * chain::POWER[link];
                            i32 excess = 0;
                            for (i32 link = 1; link < result.chain.count; ++link)
                                excess += std::max(0, i32(result.popped[link]) - 4);
                            value += result.chain.score - pure - excess * 10 * chain::POWER[std::min(result.chain.count, 18)];
                        }
                        expected_eval = std::max(expected_eval, value);
                    }
                    beam::node::Data node;
                    node.field = original;
                    beam::eval::evaluate(node, weight);
                    check(node.score.eval == (scored.empty() ? 0 : expected_eval),
                          "evaluation retains detailed efficiency and count-only behavior");
                }
                quiet_results += i32(scored.size());
            }
        }
        check(quiet_results > 100, "random fields exercise quiet chain extensions");
        std::cout << "Core speed regression checks passed: 2000 scalar fields, 500 quiet fields, "
                  << quiet_results << " quiet candidates\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
