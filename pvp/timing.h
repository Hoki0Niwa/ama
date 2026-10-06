#pragma once

// Referee time is in game frames. Search still uses its original abstract units.
struct Timing
{
    i32 fps = 60;
    i32 start = 11;
    i32 soft_drop = 2;
    i32 input = 3;
    i32 wall_kick = 9;
    i32 quick_turn = 8;
    i32 next_pair = 27;
    i32 tear_row = 18;
    i32 vanish = 55;
    i32 chain_drop = 2;
    i32 chain_ground = 23;
    i32 garbage_drop = 2;
    i32 garbage_ground = 32;
    i32 ai_unit = 41; // observed median link interval (82 frames) / 2

    json to_json() const
    {
        return {{"fps", fps}, {"start", start}, {"soft_drop", soft_drop},
            {"input", input}, {"wall_kick", wall_kick}, {"quick_turn", quick_turn},
            {"next_pair", next_pair}, {"tear_row", tear_row}, {"vanish", vanish},
            {"chain_drop", chain_drop}, {"chain_ground", chain_ground},
            {"garbage_drop", garbage_drop}, {"garbage_ground", garbage_ground},
            {"ai_unit", ai_unit}};
    }

    void load(const std::string& filename)
    {
        std::ifstream file(filename);
        if (!file) throw std::runtime_error("can't open timing profile: " + filename);
        json js;
        file >> js;
        if (!js.is_object()) throw std::runtime_error("timing profile must be an object");
        auto defaults = to_json();
        for (auto it = js.begin(); it != js.end(); ++it) {
            if (it.key() == "description" || it.key() == "sources") continue;
            if (!defaults.contains(it.key())) throw std::runtime_error("unknown timing key: " + it.key());
            if (!it.value().is_number_integer() || it.value() < 0 || it.value() > 10000)
                throw std::runtime_error("timing must be an integer in 0..10000: " + it.key());
            defaults[it.key()] = it.value();
        }
        fps = defaults["fps"]; start = defaults["start"]; soft_drop = defaults["soft_drop"];
        input = defaults["input"]; wall_kick = defaults["wall_kick"]; quick_turn = defaults["quick_turn"];
        next_pair = defaults["next_pair"]; tear_row = defaults["tear_row"]; vanish = defaults["vanish"];
        chain_drop = defaults["chain_drop"]; chain_ground = defaults["chain_ground"];
        garbage_drop = defaults["garbage_drop"]; garbage_ground = defaults["garbage_ground"];
        ai_unit = defaults["ai_unit"];
        if (fps == 0 || soft_drop == 0 || input == 0 || vanish == 0 || ai_unit == 0)
            throw std::runtime_error("fps, soft_drop, input, vanish and ai_unit must be positive");
    }

    i32 to_ai(i32 frames) const { return (std::max(0, frames) + ai_unit - 1) / ai_unit; }

    // Short paths are cheap compared with a beam search. Keep DOWN held on low
    // fields; above a stack, finish steering before starting the soft drop.
    i32 placement_frames(Field& field, const move::Placement& goal,
                         cell::Pair pair = {cell::Type::RED, cell::Type::BLUE}) const
    {
        u8 heights[6];
        field.get_heights(heights);
        struct Node { path::Position pos; i32 frames; };
        std::vector<Node> open = {{path::Position(2, 11, direction::Type::UP), 0}};
        i32 best[6][5][4];
        for (auto& column : best) for (auto& row : column) std::fill(std::begin(row), std::end(row), std::numeric_limits<i32>::max());
        best[2][0][0] = 0;
        i32 duration = std::numeric_limits<i32>::max();
        path::Position target(goal.x, 11, goal.r);
        if (pair.first == pair.second) target.normalize();
        // Dijkstra over the existing collision/rotation model. Strictly better
        // visits avoid enumerating many equivalent shortest input sequences.
        while (!open.empty()) {
            auto next = std::min_element(open.begin(), open.end(), [](const Node& a, const Node& b) { return a.frames < b.frames; });
            auto node = *next;
            open.erase(next);
            auto pos = node.pos;
            if (node.frames >= duration) break;
            if (node.frames != best[pos.x][pos.y - 11][static_cast<i32>(pos.r)]) continue;
            auto canonical = pos;
            if (pair.first == pair.second) canonical.normalize();
            if (canonical.x == target.x && canonical.r == target.r) {
                i32 child_x = pos.x + direction::get_offset_x(pos.r);
                i32 resting_y = std::max(i32(heights[pos.x]),
                                       i32(heights[child_x]) - direction::get_offset_y(pos.r));
                i32 fall = std::max(0, i32(pos.y) - resting_y) * soft_drop;
                i32 frames = path::Finder::above_stack_move(field, {pos.x, pos.r}) ? node.frames + fall : std::max(node.frames, fall);
                if (child_x != pos.x) frames += std::abs(i32(heights[pos.x]) - heights[child_x]) * tear_row;
                duration = std::min(duration, std::max(1, frames));
            }
            auto push = [&](path::Position child, bool valid, i32 cost) {
                if (!valid || child.x < 0 || child.x >= 6 || child.y < 11 || child.y > 15) return;
                auto& seen = best[child.x][child.y - 11][static_cast<i32>(child.r)];
                if (node.frames + cost >= seen) return;
                seen = node.frames + cost;
                open.push_back({child, seen});
            };
            auto child = pos; bool valid = child.move_left(field, heights); push(child, valid, input);
            child = pos; valid = child.move_right(field, heights); push(child, valid, input);
            child = pos; valid = child.move_cw(field, heights); push(child, valid, child.x != pos.x ? wall_kick : input);
            child = pos; valid = child.move_ccw(field, heights); push(child, valid, child.x != pos.x ? wall_kick : input);
            child = pos; valid = child.move_180(field, heights); push(child, valid, 2 * input + quick_turn);
        }
        return duration == std::numeric_limits<i32>::max() ? -1 : duration;
    }
};

struct ChainLink
{
    i32 score = 0;
    i32 frames = 0;
};

// Resolve once per actual placement, retaining each link's score and fall
// distance. The search hot path and Field::pop remain unchanged.
inline std::vector<ChainLink> resolve_timed_chain(Field& field, const Timing& timing)
{
    std::vector<ChainLink> links;
    for (i32 index = 0; index < 19; ++index) {
        auto popped = field.get_mask_pop();
        auto mask = popped.get_mask();
        if (mask.is_empty()) break;
        avec<Field, 19> scoring;
        for (i32 i = 0; i < index; ++i) scoring.add(Field());
        scoring.add(popped);
        i32 score = chain::get_score(scoring).score;
        mask = mask | (mask.get_expand() & field.data[static_cast<u8>(cell::Type::GARBAGE)]);
        i32 distance = 0;
        for (i8 x = 0; x < 6; ++x) {
            i32 holes = 0;
            for (i8 y = 0; y < 13; ++y) {
                if (mask.get_bit(x, y)) ++holes;
                else if (field.get_cell(x, y) != cell::Type::NONE) distance = std::max(distance, holes);
            }
        }
        for (u8 color = 0; color < cell::COUNT; ++color) field.data[color].pop(mask);
        links.push_back({score, timing.vanish + (distance ? timing.chain_ground + distance * timing.chain_drop : 0)});
    }
    return links;
}

// Referee garbage must conserve puyos. Field::drop_garbage is an AI worst-case
// estimate (including a duplicated remainder of one), so do not use it here.
inline i32 drop_match_garbage(Field& field, i32 count, u32& rng)
{
    i32 distance = 0;
    for (i8 x = 0; x < 6; ++x) {
        if (count >= 6) distance = std::max(distance, 13 - i32(field.get_height(x)));
        for (i32 row = 0; row < count / 6; ++row) field.drop_puyo(x, cell::Type::GARBAGE);
    }
    std::array<i8, 6> columns = {0, 1, 2, 3, 4, 5};
    for (i32 i = 5; i > 0; --i) {
        rng = rng * u32(0x5D588B65) + u32(0x269EC3);
        std::swap(columns[i], columns[(rng >> 16) % (i + 1)]);
    }
    for (i32 i = 0; i < count % 6; ++i) {
        distance = std::max(distance, 13 - i32(field.get_height(columns[i])));
        field.drop_puyo(columns[i], cell::Type::GARBAGE);
    }
    return std::max(0, distance);
}
