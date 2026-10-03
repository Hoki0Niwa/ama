#include "../ai/search/beam/eval.h"
#include <iostream>
#include <stdexcept>

void check(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

int main()
{
    try {
        check(beam::form::COUNT == 3, "main's three active forms are restored");
        beam::eval::Weight weight;
        json legacy = weight;
        legacy.erase("form");
        weight.form = 50;
        legacy.get_to(weight);
        check(weight.form == 0, "legacy weights reset form to off");
        json enabled = legacy;
        enabled["form"] = 50;
        enabled.get_to(weight);
        check(weight.form == 50, "form weight loads from JSON");
        check(json(weight).at("form") == 50, "form weight round trips");

        beam::node::Data node;
        node.field.set_cell(0, 0, cell::Type::GREEN);
        node.field.set_cell(1, 0, cell::Type::GREEN);
        node.field.set_cell(0, 1, cell::Type::RED);
        node.field.set_cell(1, 1, cell::Type::RED);
        u8 heights[6];
        node.field.get_heights(heights);
        check(beam::form::evaluate(node.field, heights, beam::form::GTR) > 0, "partial GTR matches");
        i32 best = -100;
        for (const auto& pattern : beam::form::list) {
            best = std::max(best, beam::form::evaluate(node.field, heights, pattern));
        }
        beam::eval::evaluate(node, weight);
        check(node.score.eval == best * 50, "enabled evaluation adds best matching form times weight");
        weight.form = 0;
        beam::eval::evaluate(node, weight);
        check(node.score.eval == 0, "off adds no bias");

        weight.form = 50;
        node.field.set_cell(0, 0, cell::Type::GARBAGE);
        beam::eval::evaluate(node, weight);
        check(node.score.eval == 0, "bottom-left garbage suspends matching as in main");

        node = beam::node::Data();
        for (i8 x = 0; x < 2; ++x) {
            for (i8 y = 0; y < 2; ++y) node.field.set_cell(x, y, cell::Type::RED);
        }
        beam::eval::evaluate(node, weight);
        check(node.score.eval == -5000, "incompatible colors receive main's mismatch penalty");
        std::cout << "Optional form evaluation checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
