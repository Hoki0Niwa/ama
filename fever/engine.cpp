#include "engine.h"
#include "fire.h"
#include "text.h"
#include <chrono>
#include <fstream>

namespace fever
{

namespace
{

json fail(const std::string& message)
{
    return json{ {"error", message} };
};

};

json answer(const json& input, const beam::eval::Weight& w, const json& set)
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
    configs.hill = set.value("hill", 0);
    configs.stock = set.value("stock", 0);
    configs.stock_color = set.value("stock_color", 0);
    configs.stock_want = std::clamp(input.value("stock_want", configs.stock_want), 1, 7);
    configs.aim = input.value("aim", false);

    configs.trigger = input.value("trigger", configs.trigger);
    configs.build_chain = input.value("build_chain", 0);
    configs.preserve_build = input.value("preserve_build", false);
    // Legacy budget_ms input is ignored: complete the configured construction search.
    configs.stretch = input.value("stretch", configs.stretch);
    configs.panic_count = input.value("panic_count", configs.panic_count);
    configs.panic_chain = input.value("panic_chain", configs.panic_chain);
    configs.shave_chain = input.value("shave_chain", configs.shave_chain);
    configs.rules.plain_pairs = input.value("plain_pairs", false);
    configs.rules.special_moves = input.value("special_moves", false);
    configs.rules.margin = u8(std::clamp(input.value("margin", 0), 0, 6));
    configs.panic_step = input.value("panic_step", configs.panic_step);
    configs.moves = input.value("moves", 0);
    configs.patience = input.value("patience", configs.patience);
    configs.patience_step = input.value("patience_step", configs.patience_step);
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

        if (!choice && configs.rules.margin) {
            // Nothing stays within the margin (the board is already above it): play on by the rule alone
            configs.rules.margin = 0;
            choice = fever::think(*field, queue, *character, u64(index), w, configs);
        }
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
    if (!choice->search_depths.empty()) {
        output["search_virtual_depths"] = choice->search_depths;
        output["search_completed_depth"] = *std::min_element(choice->search_depths.begin(),choice->search_depths.end());
    }

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

bool load_weights(const std::string& path, beam::eval::Weight& w, json& set)
{
    std::ifstream file(path);

    if (!file.good()) {
        return false;
    }

    json js;
    file >> js;

    // The fever set where the file has one (it may carry the fever-only weight "hill"), else the Tsu long-chain set
    set = js.contains("fever") ? js.at("fever") : js.at("build");
    from_json(set, w);

    return true;
};

};
