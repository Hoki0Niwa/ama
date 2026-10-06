#include "engine.h"
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
// - "plain_pairs": true offers pairs only where they get without kicks or climbing (for a real client).
// - "margin": rows the search keeps free below the 12th in the death columns (0-6, default 0). When nothing
//   stays within it, the move is chosen by the rule alone.
// - "moves", "patience", "patience_step": the number of pieces placed so far in the build, and the number
//   from which the chain length that is fired falls by one link every patience_step pieces (0 = never).
// - "include_next" adds the field after the placement and the chain it pops.
// - Garbage, the fever gauge and the opponent aren't modelled: only "solo": true is accepted.
int main(int argc, char** argv)
{
    std::string config_path = argc > 1 ? argv[1] : "config.json";

    beam::eval::Weight w;
    json set;

    if (!fever::load_weights(config_path, w, set)) {
        fprintf(stderr, "can't open \"%s\"\n", config_path.c_str());
        return 1;
    }

    std::string line;

    while (std::getline(std::cin, line))
    {
        if (line.empty()) {
            continue;
        }

        json output;

        try {
            output = fever::answer(json::parse(line), w, set);
        }
        catch (const std::exception& e) {
            output = json{ {"error", e.what()} };
        }

        std::cout << output.dump() << std::endl;
    }

    return 0;
};
