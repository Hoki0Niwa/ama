#include "fire.h"
#include "text.h"
#include <iostream>

// Fever engine, stage A: solo chain building only
//
// Serves a JSON line protocol on stdin/stdout, one request and one reply per line, in the same
// spirit as `pvp --engine`. It is a separate binary so that a Tsu client can't run it by mistake:
// a request without "rule": "fever" is refused.
//
//   request: { "rule": "fever", "character": "raffina", "dropset_index": 0, "solo": true,
//              "self": { "field": [14 strings, 14th row first], "queue": ["2:RG", "2:BY", "L:RRG"] },
//              "trigger": 14, "stretch": true, "beam_width": 250, "beam_depth": 16,
//              "fire": false, "include_next": false }
//   reply:   { "x": 2, "r": "U", "shape": "2", "chain": 0, "eval": 0, "fire": false, "solo": true }
//   error:   { "error": "..." }
//
// - "dropset_index" is the zero-based move of the character's cycle that queue[0] is. Every piece of
//   the queue must have the shape the cycle gives, otherwise the request is refused.
// - "queue" holds the visible pieces, see fever/text.h for their text form.
// - "trigger" is a chain length. A chain that long within the visible pieces is fired: "fire" is
//   true and "fire_moves" is the number of pieces until it pops (1 when this placement pops it).
//   "panic_count", "panic_chain", "panic_step" and "shave_chain" set the other firing rules, see fever/search.h.
// - "fire": true asks for the longest chain the piece in hand triggers right away.
// - "x" is the pivot's column for a pair and the left column of the 2x2 box for the other shapes.
//   "r" is the clockwise turns as U/R/D/L. For a big puyo "r" is its color index (U red, R yellow,
//   D green, L blue) and "color" repeats it as a color character.
// - "include_next" adds the field after the placement and the chain it pops.
// - Garbage, the fever gauge and the opponent aren't modelled: only "solo": true is accepted.
namespace
{

json fail(const std::string& message)
{
    return json{ {"error", message} };
};

json answer(const json& input, const beam::eval::Weight& w)
{
    if (input.value("rule", "") != "fever") {
        return fail("rule must be \"fever\"");
    }

    if (!input.value("solo", false)) {
        return fail("only solo requests are supported");
    }

    const auto id = input.value("character", "");
    const auto* character = dropset::find(id);

    if (character == nullptr) {
        return fail("unknown character \"" + id + "\"");
    }

    const auto index = input.value("dropset_index", i64(-1));

    if (index < 0) {
        return fail("dropset_index is missing or negative");
    }

    if (!input.contains("self") || !input["self"].contains("field") || !input["self"].contains("queue")) {
        return fail("self.field and self.queue are required");
    }

    auto field = fever::text::to_field(input["self"]["field"].get<std::vector<std::string>>());

    if (!field) {
        return fail("field must be 14 rows of 6 cells without floating cells");
    }

    fever::Queue queue;

    for (auto& str : input["self"]["queue"].get<std::vector<std::string>>()) {
        auto value = fever::text::to_piece(str);
        auto drop = dropset::drop_at(*character, u64(index) + queue.size());

        if (!value) {
            return fail("invalid piece \"" + str + "\"");
        }

        if (!drop || !fever::text::is_matching(*value, *drop)) {
            return fail("piece \"" + str + "\" isn't move " + std::to_string(index + i64(queue.size())) + " of the cycle");
        }

        queue.push_back(*value);
    }

    if (queue.empty()) {
        return fail("queue is empty");
    }

    auto configs = fever::Configs();

    configs.trigger = input.value("trigger", configs.trigger);
    configs.stretch = input.value("stretch", configs.stretch);
    configs.panic_count = input.value("panic_count", configs.panic_count);
    configs.panic_chain = input.value("panic_chain", configs.panic_chain);
    configs.shave_chain = input.value("shave_chain", configs.shave_chain);
    configs.panic_step = input.value("panic_step", configs.panic_step);
    configs.width = std::clamp(input.value("beam_width", configs.width), size_t(1), size_t(100000));
    configs.depth = std::clamp(input.value("beam_depth", configs.depth), queue.size(), size_t(64));

    const auto started = std::chrono::steady_clock::now();

    std::optional<fever::Choice> choice = {};

    if (input.value("fire", false)) {
        auto now = fever::fire::best_now(*field, queue[0], configs.rules);

        if (now) {
            choice = fever::Choice {
                .placement = now->placement,
                .chain = now->chain.count,
                .score = size_t(now->chain.score),
                .fire = true,
                .fire_moves = 1
            };
        }
    }
    else {
        choice = fever::think(*field, queue, *character, u64(index), w, configs);
    }

    if (!choice) {
        return fail("no placement survives");
    }

    json output;

    output["x"] = choice->placement.x;
    output["r"] = std::string(1, fever::text::from_direction(choice->placement.r));
    output["shape"] = fever::text::from_piece(queue[0]).substr(0, 1);
    output["chain"] = choice->chain;
    output["eval"] = choice->score;
    output["fire"] = choice->fire;

    if (choice->fire) {
        output["fire_moves"] = choice->fire_moves;
    }
    output["solo"] = true;

    if (queue[0].shape == piece::Shape::BIG) {
        output["color"] = std::string(1, cell::to_char(cell::Type(static_cast<u8>(choice->placement.r))));
    }

    if (input.value("include_next", false)) {
        auto after = *field;
        auto drop = after.drop_piece(choice->placement.x, choice->placement.r, queue[0], configs.rules);
        auto pop = after.pop();
        auto chain = chain::get_score(pop);

        output["next_chain"] = chain.count;
        output["next_score"] = chain.score;
        output["next_discarded"] = drop ? drop->discarded : 0;
        output["next_all_clear"] = after.is_empty();
        output["next_field"] = fever::text::from_field(after);
    }

    output["search_ms"] = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();

    return output;
};

};

int main(int argc, char** argv)
{
    std::string config_path = argc > 1 ? argv[1] : "config.json";

    beam::eval::Weight w;
    {
        std::ifstream file(config_path);

        if (!file.good()) {
            fprintf(stderr, "can't open \"%s\"\n", config_path.c_str());
            return 1;
        }

        json js;
        file >> js;

        // The Tsu weights are the starting point until the fever ones are tuned
        from_json(js.contains("fever") ? js.at("fever") : js.at("build"), w);
    }

    std::string line;

    while (std::getline(std::cin, line))
    {
        if (line.empty()) {
            continue;
        }

        json output;

        try {
            output = answer(json::parse(line), w);
        }
        catch (const std::exception& e) {
            output = fail(e.what());
        }

        std::cout << output.dump() << std::endl;
    }

    return 0;
};
