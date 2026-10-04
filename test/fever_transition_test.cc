#include "../core/move.h"
#include <random>
#include <stdexcept>

namespace
{
using C = cell::Type;
constexpr C R = C::RED, G = C::GREEN, B = C::BLUE, N = C::NONE;
using Grid = std::array<std::array<C, 6>, 13>;
struct Blob { int x, y; C color; };
struct Reference { Grid grid; int retained, discarded; bool split; };
int comparisons = 0;

void check(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

Grid empty_grid()
{
    Grid grid;
    for (auto& row : grid) row.fill(N);
    return grid;
}

Field to_field(const Grid& grid)
{
    Field field;
    for (int y = 0; y < 13; ++y) for (int x = 0; x < 6; ++x)
        if (grid[y][x] != N) field.set_cell(i8(x), i8(y), grid[y][x]);
    return field;
}

Grid to_grid(Field& field)
{
    auto grid = empty_grid();
    for (int y = 0; y < 13; ++y) for (int x = 0; x < 6; ++x)
        grid[y][x] = field.get_cell(i8(x), i8(y));
    return grid;
}

// Fixed diagrams, independent of the production geometry transformation.
std::vector<Blob> diagram(const piece::Piece& value, int r)
{
    if (value.shape == piece::Shape::PAIR) {
        constexpr int dx[4] = { 0, 1, 0, -1 }, dy[4] = { 1, 0, -1, 0 };
        return { { 0, 0, value.colors[0] }, { dx[r], dy[r], value.colors[1] } };
    }
    if (value.shape == piece::Shape::TRIPLE) {
        constexpr int positions[4][3][2] = {
            {{0,0},{0,1},{1,0}}, {{0,1},{1,1},{0,0}},
            {{1,1},{1,0},{0,1}}, {{1,0},{0,0},{1,1}}
        };
        std::vector<Blob> result;
        for (int i = 0; i < 3; ++i) result.push_back({positions[r][i][0], positions[r][i][1], value.colors[i]});
        return result;
    }
    constexpr int positions[4][4][2] = {
        {{0,0},{0,1},{1,0},{1,1}}, {{0,1},{1,1},{0,0},{1,0}},
        {{1,1},{1,0},{0,1},{0,0}}, {{1,0},{0,0},{1,1},{0,1}}
    };
    std::vector<Blob> result;
    for (int i = 0; i < 4; ++i)
        result.push_back({positions[value.shape == piece::Shape::BIG ? 0 : r][i][0],
                          positions[value.shape == piece::Shape::BIG ? 0 : r][i][1],
                          value.shape == piece::Shape::BIG ? C(r) : value.colors[i]});
    return result;
}

bool collides(const Grid& grid, const std::vector<Blob>& blobs, int x, int y)
{
    for (const auto& blob : blobs) {
        const int cx = x + blob.x, cy = y + blob.y;
        if (cx < 0 || cx >= 6 || cy < 0 || cy > 14) return true;
        if (cy < 13 && grid[cy][cx] != N) return true;
    }
    return false;
}

std::optional<Reference> reference_drop(Grid grid, const piece::Piece& value, int x, int r,
                                       const rule::Rule& rules)
{
    auto blobs = diagram(value, r);
    for (const auto& blob : blobs) if (x + blob.x < 0 || x + blob.x >= 6) return std::nullopt;
    // Lower a rigid shape from well above the field to its first contact.
    int anchor = 20;
    const auto supported = [&](int y) {
        for (const auto& blob : blobs) {
            const int cy = y + blob.y;
            if (cy < 0 || (cy < 13 && grid[cy][x + blob.x] != N)) return true;
        }
        return false;
    };
    while (!supported(anchor - 1)) --anchor;
    for (auto& blob : blobs) {
        blob.x += x; blob.y += anchor;
        if (blob.y > 14) return std::nullopt;
    }
    std::sort(blobs.begin(), blobs.end(), [](const Blob& a, const Blob& b) { return a.y < b.y; });
    bool split = false;
    auto virtual_grid = std::array<std::array<C, 6>, 15>{};
    for (auto& row : virtual_grid) row.fill(N);
    for (int y = 0; y < 13; ++y) virtual_grid[y] = grid[y];
    for (const auto& blob : blobs) {
        int y = blob.y;
        while (y > 0 && virtual_grid[y - 1][blob.x] == N) --y;
        split |= y != blob.y;
        virtual_grid[y][blob.x] = blob.color;
    }
    int retained = 0, discarded = 0;
    for (const auto& blob : blobs) {
        if (rules.overflow == rule::Overflow::ON_CONTACT && blob.y >= 13) { ++discarded; continue; }
        int y = blob.y;
        while (y > 0 && (y - 1 >= 13 || grid[y - 1][blob.x] == N)) --y;
        if (y >= 13) { ++discarded; continue; }
        grid[y][blob.x] = blob.color;
        ++retained;
    }
    return Reference{ grid, retained, discarded, split };
}

// Flood fill visible rows only, remove adjacent garbage, and compact columns.
int reference_pop(Grid& grid)
{
    int chains = 0;
    while (true) {
        bool seen[12][6]{}, erase[13][6]{};
        bool any = false;
        for (int y = 0; y < 12; ++y) for (int x = 0; x < 6; ++x) {
            if (seen[y][x] || grid[y][x] == N || grid[y][x] == C::GARBAGE) continue;
            std::vector<std::pair<int,int>> group{{x,y}};
            seen[y][x] = true;
            for (usize head = 0; head < group.size(); ++head) {
                const auto [gx, gy] = group[head];
                for (const auto [dx,dy] : {std::pair{1,0},{-1,0},{0,1},{0,-1}}) {
                    const int nx = gx + dx, ny = gy + dy;
                    if (nx < 0 || nx >= 6 || ny < 0 || ny >= 12 || seen[ny][nx] || grid[ny][nx] != grid[y][x]) continue;
                    seen[ny][nx] = true;
                    group.emplace_back(nx,ny);
                }
            }
            if (group.size() < 4) continue;
            any = true;
            for (const auto [gx,gy] : group) {
                erase[gy][gx] = true;
                for (const auto [dx,dy] : {std::pair{1,0},{-1,0},{0,1},{0,-1}}) {
                    const int nx = gx + dx, ny = gy + dy;
                    if (nx >= 0 && nx < 6 && ny >= 0 && ny < 13 && grid[ny][nx] == C::GARBAGE) erase[ny][nx] = true;
                }
            }
        }
        if (!any) break;
        ++chains;
        for (int x = 0; x < 6; ++x) {
            int next = 0;
            for (int y = 0; y < 13; ++y) if (!erase[y][x] && grid[y][x] != N) grid[next++][x] = grid[y][x];
            while (next < 13) grid[next++][x] = N;
        }
    }
    return chains;
}

void compare_transition(const Grid& grid, const piece::Piece& value, int x, int r, const rule::Rule& rules)
{
    auto actual = to_field(grid);
    const auto original = actual;
    const auto expected = reference_drop(grid, value, x, r, rules);
    const auto frame = actual.get_drop_piece_frame(i8(x), direction::Type(r), value, rules);
    const auto result = actual.drop_piece(i8(x), direction::Type(r), value, rules);
    check(result.has_value() == expected.has_value() && frame.has_value() == expected.has_value(), "placement validity");
    if (!result) { check(actual == original, "invalid placement mutated field"); return; }
    check(result->retained == expected->retained && result->discarded == expected->discarded, "overflow counts");
    check(result->retained + result->discarded == piece::cell_count(value.shape), "cell conservation");
    check(result->split == expected->split && *frame == 1 + expected->split, "split cost");
    check(to_grid(actual) == expected->grid && actual.row14 == 0, "landing/color order");
    auto scalar = expected->grid;
    const auto chains = reference_pop(scalar);
    auto counted = actual;
    check(actual.pop().get_size() == chains && counted.pop_count() == chains, "chain length");
    check(to_grid(actual) == scalar && to_grid(counted) == scalar, "chain final grid");
    ++comparisons;
}

// Independent graph closure by repeated scans, using fixed pivot diagrams.
std::array<std::array<bool,4>,5> reference_reach(const Grid& grid, const piece::Piece& value)
{
    bool state[5][15][4]{};
    std::array<std::array<bool,4>,5> result{};
    const int initial = value.shape == piece::Shape::BIG ? int(value.colors[0]) : 0;
    if (collides(grid, diagram(value, initial), 2, 11)) return result;
    state[2][11][initial] = true;
    constexpr int px[4] = {0,0,1,1}, py[4] = {0,1,1,0};
    bool changed = true;
    while (changed) {
        changed = false;
        for (int x = 0; x < 5; ++x) for (int y = 0; y < 15; ++y) for (int r = 0; r < 4; ++r) {
            if (!state[x][y][r]) continue;
            const auto add = [&](int nx, int ny, int nr) {
                if (nx < 0 || nx >= 5 || ny < 0 || ny >= 15 || state[nx][ny][nr]) return;
                if (collides(grid, diagram(value,nr), nx,ny)) return;
                state[nx][ny][nr] = true; changed = true;
            };
            add(x - 1,y,r); add(x + 1,y,r); add(x,y - 1,r);
            for (int nr : {(r + 1) % 4,(r + 3) % 4}) {
                const bool triple = value.shape == piece::Shape::TRIPLE;
                add(x + (triple ? px[r] - px[nr] : 0), y + (triple ? py[r] - py[nr] : 0),nr);
            }
        }
    }
    for (int x = 0; x < 5; ++x) for (int y = 0; y < 15; ++y) for (int r = 0; r < 4; ++r)
        result[x][r] = result[x][r] || state[x][y][r];
    return result;
}
}

int main()
{
    try {
        const std::array<piece::Piece, 7> pieces = {{
            piece::from_pair({R,B}), piece::from_pair({R,R}),
            {piece::Shape::TRIPLE,{R,R,B,N}}, {piece::Shape::TRIPLE,{R,B,R,N}},
            {piece::Shape::TRIPLE,{R,R,R,N}}, {piece::Shape::QUAD,{R,R,B,B}},
            {piece::Shape::BIG,{G,N,N,N}}
        }};
        auto empty = empty_grid();
        auto empty_field = to_field(empty);
        for (usize i = 0; i < pieces.size(); ++i) {
            auto placements = move::generate(empty_field,pieces[i]);
            check(placements.get_size() == (i == 0 ? 22 : i == 1 ? 11 : 20), "empty-field candidates");
        }
        for (const auto& value : pieces) for (int r = 0; r < 4; ++r) for (int x = -1; x <= 6; ++x)
            compare_transition(empty,value,x,r,rule::FEVER);
        // Every height combination in a two-column ledge, including overflow.
        for (int left = 0; left <= 13; ++left) for (int right = 0; right <= 13; ++right) {
            auto grid = empty_grid();
            for (int y = 0; y < left; ++y) grid[y][0] = C::GARBAGE;
            for (int y = 0; y < right; ++y) grid[y][1] = C::GARBAGE;
            for (const auto& value : pieces) for (int r = 0; r < 4; ++r)
                for (const auto& rules : {rule::FEVER,rule::FEVER_CONTACT}) compare_transition(grid,value,0,r,rules);
        }
        std::mt19937 random(20261004);
        for (int trial = 0; trial < 256; ++trial) {
            auto grid = empty_grid();
            for (int x = 0; x < 6; ++x) {
                const int height = random() % (x == 2 || x == 3 ? 12 : 14);
                for (int y = 0; y < height; ++y) grid[y][x] = C(random() % 5);
            }
            for (const auto& value : pieces) {
                auto field = to_field(grid);
                u8 heights[6];
                field.get_heights(heights);
                for (int r = 0; r < 4; ++r) for (int x = -1; x <= 6; ++x) for (int y = 10; y <= 15; ++y) {
                    const bool expected_collision = collides(grid,diagram(value,r),x,y);
                    check(field.is_colliding_piece(i8(x),i8(y),direction::Type(r),value) == expected_collision,
                          "Fever collision geometry");
                    check(field.is_colliding_piece(i8(x),i8(y),direction::Type(r),value,heights) == expected_collision,
                          "cached Fever collision geometry");
                }
                for (int r = 0; r < 4; ++r) for (int x = 0; x < 6; ++x)
                    compare_transition(grid,value,x,r,rule::FEVER);
                if (value.shape == piece::Shape::PAIR) continue;
                const auto expected = reference_reach(grid,value);
                auto placements = move::generate(field,value);
                auto actual = std::array<std::array<bool,4>,5>{};
                for (int i = 0; i < placements.get_size(); ++i) {
                    const auto p = placements[i];
                    check(p.x >= 0 && p.x < 5 && !actual[p.x][int(p.r)], "duplicate/outside special placement");
                    actual[p.x][int(p.r)] = true;
                    check(field.drop_piece(p.x,p.r,value).has_value(), "reachable placement cannot drop");
                    field = to_field(grid);
                }
                check(actual == expected, "conservative reachability mismatch");
            }
        }
        // Fix the public boundary convention with explicit expected diagrams.
        auto cliff = empty_grid();
        for (int y = 0; y < 13; ++y) cliff[y][4] = C::GARBAGE;
        auto wall = to_field(cliff);
        for (const auto& value : {pieces[2],pieces[5],pieces[6]}) {
            auto placements = move::generate(wall,value);
            for (int i = 0; i < placements.get_size(); ++i)
                check(placements[i].x < 4, "crossed full-height wall");
        }
        // QUAD/BIG rotations change colors only. Neither can use a pivot shift
        // or kick to climb the 12th/13th row wall on either side of spawn.
        for (int height : {12,13}) for (int barrier : {1,4}) {
            auto grid = empty_grid();
            for (int y = 0; y < height; ++y) grid[y][barrier] = C::GARBAGE;
            auto field = to_field(grid);
            for (const auto& value : {pieces[5],pieces[6]}) {
                for (int r = 0; r < 4; ++r) {
                    const auto geometry = *piece::geometry(value,direction::Type(r));
                    check(geometry.pivot_x == 0 && geometry.pivot_y == 0, "four-cell pivot shift");
                    for (int x = 0; x < 5; ++x)
                        check(field.is_colliding_piece(i8(x),11,direction::Type(r),value) ==
                              field.is_colliding_piece(i8(x),11,direction::Type::UP,value), "rotation changed four-cell footprint");
                }
                auto placements = move::generate(field,value);
                if (placements.get_size() != 12)
                    std::cerr << "wall height=" << height << " column=" << barrier
                              << " shape=" << int(value.shape) << " candidates=" << placements.get_size() << '\n';
                check(placements.get_size() == 12, "four-cell wall candidates");
                for (int i = 0; i < placements.get_size(); ++i)
                    check(barrier == 1 ? placements[i].x >= 2 : placements[i].x <= 2,
                          "four-cell rotation crossed high wall");
            }
        }
        auto blocked_spawn = empty_grid();
        for (int y = 0; y < 13; ++y) blocked_spawn[y][3] = C::GARBAGE;
        auto blocked = to_field(blocked_spawn);
        check(!blocked.is_dead(rule::TSU) && blocked.is_dead(rule::FEVER), "fourth death column");
        for (const auto& value : pieces) check(move::generate(blocked,value).get_size() == 0, "moves after Fever death");
        auto saved = empty_grid();
        for (int y = 0; y < 11; ++y) saved[y][3] = y >= 8 ? R : C::GARBAGE;
        auto rescue = to_field(saved);
        check(rescue.drop_piece(3,direction::Type::UP,pieces[1]).has_value(), "rescue placement");
        check(rescue.is_dead(rule::FEVER), "pre-pop death flag");
        check(rescue.pop_count() == 1 && !rescue.is_dead(rule::FEVER), "death checked before pop");
        auto hidden = empty_grid();
        for (int y = 0; y < 13; ++y) hidden[y][0] = y >= 9 ? R : C::GARBAGE;
        auto hidden_field = to_field(hidden);
        check(hidden_field.pop_count() == 0, "row 13 joined visible group");
        auto full = empty_grid();
        for (int y = 0; y < 13; ++y) full[y][0] = full[y][1] = C::GARBAGE;
        auto discard = to_field(full);
        const auto before = discard;
        for (int repeat = 0; repeat < 3; ++repeat) {
            const auto result = discard.drop_piece(0,direction::Type::UP,pieces[5]);
            check(result && result->discarded == 4 && result->retained == 0 && discard == before, "repeat full discard");
        }
        // Both timing models must remain observably different on an upper ledge.
        auto ledge = empty_grid();
        for (int y = 0; y < 13; ++y) ledge[y][0] = C::GARBAGE;
        auto after = to_field(ledge), contact = after;
        const auto a = after.drop_piece(0,direction::Type::RIGHT,pieces[0],rule::FEVER);
        const auto b = contact.drop_piece(0,direction::Type::RIGHT,pieces[0],rule::FEVER_CONTACT);
        check(a && b && a->discarded == 1 && b->discarded == 2, "overflow timing switch");
        auto invalid = to_field(empty), unchanged = invalid;
        check(!invalid.drop_piece(0,direction::Type(255),pieces[0]), "invalid rotation accepted");
        check(!invalid.drop_piece(0,direction::Type::UP,piece::Piece{}), "invalid colors accepted");
        check(invalid == unchanged, "invalid data mutation");
        invalid.row14 = 63;
        check(!invalid.is_colliding_piece(0,13,direction::Type::RIGHT,pieces[0]), "Fever row14 blocked by legacy bits");
        check(invalid.is_colliding_piece(0,13,direction::Type::RIGHT,pieces[0],rule::TSU), "Tsu ceiling changed");
        check(invalid.drop_piece(0,direction::Type::UP,pieces[0]).has_value() && invalid.row14 == 0,
              "legacy row14 leaked into Fever state");
        // Old Tsu placements/collisions/transitions stay byte-for-byte identical.
        for (int trial = 0; trial < 2000; ++trial) {
            auto grid = empty_grid();
            for (int x = 0; x < 6; ++x) {
                const int height = random() % 14;
                for (int y = 0; y < height; ++y) grid[y][x] = C(random() % 5);
            }
            auto field = to_field(grid);
            field.row14 = random() & 63;
            check(field.is_dead(rule::TSU) == (field.get_height(2) > 11), "Tsu death changed");
            for (const auto& value : {pieces[0],pieces[1]}) {
                auto old = move::generate(field,value.colors[0] == value.colors[1]);
                auto added = move::generate(field,value,rule::TSU);
                check(old.get_size() == added.get_size(), "Tsu candidate count");
                for (int i = 0; i < old.get_size(); ++i) {
                    check(old[i] == added[i], "Tsu candidate order");
                    auto legacy = field, converted = field;
                    legacy.drop_pair(old[i].x,old[i].r,*piece::to_pair(value));
                    check(converted.get_drop_piece_frame(old[i].x,old[i].r,value,rule::TSU) ==
                          field.get_drop_pair_frame(old[i].x,old[i].r), "Tsu drop cost");
                    check(converted.drop_piece(old[i].x,old[i].r,value,rule::TSU).has_value() && legacy == converted, "Tsu transition");
                }
                for (int y = 10; y <= 14; ++y) for (int x = -1; x <= 6; ++x) for (int r = 0; r < 4; ++r)
                    check(field.is_colliding_piece(i8(x),i8(y),direction::Type(r),value,rule::TSU) ==
                          field.is_colliding_pair(i8(x),i8(y),direction::Type(r)), "Tsu collision changed");
            }
        }
        std::cout << "Fever transition checks passed: " << comparisons
                  << " scalar landing/pop comparisons, 1280 special reachability comparisons, 2000 Tsu fields\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
