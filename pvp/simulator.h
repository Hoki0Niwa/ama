#pragma once

enum class Phase { READY, LOCK, LINK, CHAIN_END, GARBAGE_END, DONE };

struct FramePlayer : Player
{
    Phase phase = Phase::READY;
    move::Placement placement;
    std::vector<ChainLink> links;
    size_t link_index = 0;
    i32 remaining_score = 0;
    u32 garbage_rng = 1;

    i32 forecast(i32 target) const
    {
        return remaining_score ? (remaining_score + bonus + (all_clear ? ALL_CLEAR_BONUS * target : 0)) / target : 0;
    }
};

inline bool valid_placement(Field& field, const move::Placement& placement)
{
    i32 child = placement.x + direction::get_offset_x(placement.r);
    if (placement.x < 0 || placement.x >= 6 || child < 0 || child >= 6) return false;
    u8 heights[6];
    field.get_heights(heights);
    return move::is_valid(heights, field.row14, placement.x, placement.r);
}

// All transitions at a timestamp finish before either AI observes the state.
// Simultaneous chain links offset their incoming nuisance, then each other;
// neither the starting seat nor CPU scheduling decides who wins an exchange.
inline GameResult play_frames(Engine* engines[2], u32 seed, i32 first, const Options& options,
                             std::ostream& log, std::array<FramePlayer, 2> players = {},
                             cell::Queue queue = {})
{
    if (queue.empty()) queue = cell::create_queue(seed);
    auto& timing = options.timing;
    for (i32 p = 0; p < 2; ++p) {
        players[p].free_at = timing.start;
        players[p].garbage_rng = seed ^ (u32(p + 1) * 0x9E3779B9U);
    }
    auto finish = [&](i32 winner, const char* reason, i32 now) {
        GameResult result;
        result.winner = winner; result.reason = reason; result.ticks = now;
        for (i32 p = 0; p < 2; ++p) {
            result.moves[p] = players[p].moves;
            result.max_chain[p] = players[p].max_chain;
            result.max_score[p] = players[p].max_score;
            result.sent[p] = players[p].sent;
            result.field[p] = players[p].field;
        }
        return result;
    };
    auto emit = [&](i32 p, i32 now, json event) {
        if (options.log.empty()) return;
        event["game_seed"] = seed; event["player"] = p ? "B" : "A";
        event["tick"] = now; event["frame"] = now;
        event["move"] = players[p].moves;
        log << event.dump() << '\n';
    };
    auto view = [&](i32 p, i32 now) {
        auto& me = players[p]; auto& other = players[1 - p];
        gaze::Player result;
        result.field = me.field;
        for (i32 i = 0; i < QUEUE_VISIBLE; ++i) result.queue.push_back(queue[(me.queue_index + i) % queue.size()]);
        result.all_clear = me.all_clear;
        result.bonus = me.bonus + (me.all_clear ? ALL_CLEAR_BONUS * options.target_point : 0);
        i32 my_send = std::max(0, me.forecast(options.target_point) - me.incoming_total());
        i32 their_cancel = std::min(other.forecast(options.target_point), other.incoming_total());
        result.attack = other.incoming_total() - their_cancel + my_send;
        result.attack_chain = me.chain_end > now ? me.chain_count : 0;
        result.attack_frame = timing.to_ai(me.chain_end - now);
        result.dropping = me.chain_end > now ? 0 : me.tray;
        return result;
    };
    auto after_pair = [&](i32 p, i32 now) {
        auto& me = players[p];
        // Arrivals on this very frame are eligible. Arrivals during the
        // ensuing garbage animation wait for the following pair.
        me.settle(now);
        if (me.tray > 0) {
            i32 count = std::min(me.tray, GARBAGE_DROP_MAX);
            i32 distance = drop_match_garbage(me.field, count, me.garbage_rng);
            me.tray -= count; me.received += count;
            me.phase = Phase::GARBAGE_END;
            me.free_at = now + std::max(1, distance * timing.garbage_drop + timing.garbage_ground);
            emit(p, now, {{"event", "garbage"}, {"count", count}, {"end_frame", me.free_at}});
        }
        else {
            me.phase = me.moves >= options.max_moves ? Phase::DONE : Phase::READY;
            me.free_at = now + timing.next_pair;
        }
    };

    while (true) {
        i32 now = std::numeric_limits<i32>::max();
        for (auto& p : players) if (p.phase != Phase::DONE) now = std::min(now, p.free_at);
        if (now == std::numeric_limits<i32>::max()) return finish(-1, "max_moves", std::max(players[0].free_at, players[1].free_at));
        bool due[2];
        for (i32 p = 0; p < 2; ++p) { due[p] = players[p].phase != Phase::DONE && players[p].free_at == now; players[p].settle(now); }

        // Score both links together. Each link converts its carried score
        // pool, so partial cancellation does not lose the point remainder.
        i32 outgoing[2] = {0, 0};
        for (i32 p = 0; p < 2; ++p) {
            auto& me = players[p];
            if (!due[p] || me.phase != Phase::LINK) continue;
            auto link = me.links[me.link_index];
            i32 total = link.score + me.bonus;
            if (me.all_clear) { total += ALL_CLEAR_BONUS * options.target_point; me.all_clear = false; }
            me.bonus = total % options.target_point;
            outgoing[p] = me.offset(total / options.target_point);
            me.remaining_score -= link.score;
            ++me.link_index;
            me.free_at = now + link.frames;
            me.phase = me.link_index < me.links.size() ? Phase::LINK : Phase::CHAIN_END;
            emit(p, now, {{"event", "link"}, {"link", me.link_index}, {"score", link.score}, {"end_frame", me.free_at}});
        }
        i32 cancel = std::min(outgoing[0], outgoing[1]);
        for (i32 p = 0; p < 2; ++p) {
            i32 send = outgoing[p] - cancel;
            if (send > 0) {
                players[1 - p].incoming.push_back({send, players[p].chain_end});
                players[p].sent += send;
            }
        }
        // A link and a chain ending can share a timestamp; re-settle now,
        // before deciding whether the other player's locked pair is offsetting.
        for (auto& p : players) p.settle(now);
        bool dead[2] = {false, false};
        const char* reason = "death";
        bool check_garbage[2] = {false, false};
        for (i32 p = 0; p < 2; ++p) {
            auto& me = players[p];
            if (!due[p]) continue;
            if (me.phase == Phase::LOCK) {
                me.field.drop_pair(me.placement.x, me.placement.r, queue[me.queue_index % queue.size()]);
                ++me.queue_index;
                me.links = resolve_timed_chain(me.field, timing);
                me.link_index = 0; me.remaining_score = 0;
                for (auto link : me.links) me.remaining_score += link.score;
                emit(p, now, {{"event", "lock"}, {"chain", me.links.size()}, {"score", me.remaining_score}});
                if (!me.links.empty()) {
                    me.chain_count = i32(me.links.size());
                    me.chain_end = now;
                    for (auto link : me.links) me.chain_end += link.frames;
                    me.phase = Phase::LINK; me.free_at = now;
                    me.max_chain = std::max(me.max_chain, me.chain_count);
                    me.max_score = std::max(me.max_score, me.remaining_score);
                }
                else {
                    dead[p] = me.field.get_height(2) > 11;
                    check_garbage[p] = !dead[p];
                }
            }
            else if (me.phase == Phase::CHAIN_END && me.free_at == now) {
                if (me.field.is_empty()) me.all_clear = true;
                me.chain_count = 0; me.chain_end = 0;
                dead[p] = me.field.get_height(2) > 11;
                check_garbage[p] = !dead[p];
            }
            else if (me.phase == Phase::GARBAGE_END) {
                dead[p] = me.field.get_height(2) > 11;
                reason = "garbage";
                me.phase = me.moves >= options.max_moves ? Phase::DONE : Phase::READY;
                me.free_at = now + timing.next_pair;
            }
        }
        if (dead[0] || dead[1]) return finish(dead[0] && dead[1] ? -1 : (dead[0] ? 1 : 0), reason, now);
        for (i32 p = 0; p < 2; ++p) if (check_garbage[p]) after_pair(p, now);

        // A zero-delay link must finish before a decision at the same frame.
        bool immediate = false;
        for (auto& p : players) immediate |= p.phase == Phase::LINK && p.free_at == now;
        if (immediate) continue;

        // Capture both views before either engine's new decision is applied.
        Request requests[2]; Reply replies[2]; bool ready[2] = {false, false};
        for (i32 p = 0; p < 2; ++p) {
            auto& me = players[p];
            if (me.phase != Phase::READY || me.free_at != now) continue;
            if (me.moves >= options.max_moves) { me.phase = Phase::DONE; continue; }
            ready[p] = true;
            auto& request = requests[p];
            request.self = view(p, now); request.enemy = view(1 - p, now);
            request.target_point = options.target_point;
            request.beam_width = options.beam_width; request.beam_depth = options.beam_depth;
            i32 count = me.field.get_count();
            request.trigger = me.trigger; request.stretch = count < STRETCH_LIMIT;
            if (count >= PANIC_LIMIT_2) request.trigger = std::min(request.trigger, PANIC_TRIGGER_2);
            else if (count >= PANIC_LIMIT_1) request.trigger = std::min(request.trigger, PANIC_TRIGGER_1);
        }
        for (i32 i = 0; i < 2; ++i) { i32 p = (first + i) % 2; if (ready[p]) replies[p] = engines[p]->think(requests[p]); }
        for (i32 p = 0; p < 2; ++p) {
            if (!ready[p]) continue;
            auto& me = players[p]; auto& reply = replies[p];
            i32 duration = valid_placement(me.field, reply.placement)
                ? timing.placement_frames(me.field, reply.placement, queue[me.queue_index % queue.size()]) : -1;
            dead[p] = duration < 0;
            if (dead[p]) continue;
            me.trigger = reply.trigger.value_or(ai::TRIGGER);
            me.placement = reply.placement; ++me.moves;
            me.phase = Phase::LOCK; me.free_at = now + duration;
            auto event = request_to_json(requests[p]);
            event["event"] = "decision"; event["reply"] = reply_to_json(reply);
            event["lock_frame"] = me.free_at;
            event["enemy_attack_frames"] = std::max(0, players[1 - p].chain_end - now);
            emit(p, now, event);
        }
        if (dead[0] || dead[1]) return finish(dead[0] && dead[1] ? -1 : (dead[0] ? 1 : 0), "no_move", now);
    }
}

inline GameResult play(Engine* engines[2], u32 seed, i32 first, const Options& options, std::ostream& log)
{
    return options.frames ? play_frames(engines, seed, first, options, log) : play_abstract(engines, seed, first, options, log);
}
