#pragma once

#include <fstream>
#include <iomanip>
#include "../../../lib/nlohmann/json.hpp"
using json = nlohmann::json;

#include "node.h"
#include "form.h"
#include "quiet.h"

namespace beam
{

namespace eval
{

struct Weight
{
    i32 chain = 0;
    i32 y = 0;
    i32 key = 0;
    i32 chi = 0;

    i32 shape = 0;
    i32 well = 0;
    i32 bump = 0;
    i32 form = 0; // Optional human-form bias; zero keeps irregular-form behavior.
    i32 link_2 = 0;
    i32 link_3 = 0;
    i32 waste_14 = 0;
    i32 side = 0;
    i32 nuisance = 0;

    i32 tear = 0;
    i32 waste = 0;

    // Scales the Tsu score lost by over-sized links and gained by multi-color/large pops of the
    // planned chain, in eval points per 1,000 score points; zero keeps the chain-count-only behavior
    i32 score = 0;

    // Actual score points charged per colored puyo cleared by the candidate's
    // first move, if it is a small clear. Unknown future clears are not charged.
    // Used only to rank construction candidates; firing thresholds use the raw score.
    i32 clear_cost = 0;
};

inline void to_json(json& j, const Weight& w)
{
    j = json{
        {"chain", w.chain},
        {"y", w.y},
        {"key", w.key},
        {"chi", w.chi},
        {"shape", w.shape},
        {"well", w.well},
        {"bump", w.bump},
        {"link_2", w.link_2},
        {"link_3", w.link_3},
        {"waste_14", w.waste_14},
        {"side", w.side},
        {"nuisance", w.nuisance},
        {"tear", w.tear},
        {"waste", w.waste},
        {"form", w.form},
        {"score", w.score},
        {"clear_cost", w.clear_cost}
    };
}

inline void from_json(const json& j, Weight& w)
{
    j.at("chain").get_to(w.chain);
    j.at("y").get_to(w.y);
    j.at("key").get_to(w.key);
    j.at("chi").get_to(w.chi);
    j.at("shape").get_to(w.shape);
    j.at("well").get_to(w.well);
    j.at("bump").get_to(w.bump);
    j.at("link_2").get_to(w.link_2);
    j.at("link_3").get_to(w.link_3);
    j.at("waste_14").get_to(w.waste_14);
    j.at("side").get_to(w.side);
    j.at("nuisance").get_to(w.nuisance);
    j.at("tear").get_to(w.tear);
    j.at("waste").get_to(w.waste);
    w.form = j.value("form", 0); // Legacy configs deliberately default to off.
    w.score = j.value("score", 0);
    w.clear_cost = std::max(0, j.value("clear_cost", 0));
}


void evaluate(node::Data& node, const Weight& w);

void action(node::Data& node, i32 tear, i32 waste, const Weight& w);

i32 get_chi(u8 heights[6], i8 x);

i32 get_shape(u8 heights[6]);

i32 get_well(u8 heights[6]);

i32 get_bump(u8 heights[6]);

i32 get_u(u8 heights[6]);

i32 get_link(Field& field);

std::pair<i32, i32> get_link_23(Field& field);

i32 get_waste_14(u8 row14);

// Tsu score of a chain of `count` links popping exactly 4 puyos each
i32 get_score_pure(i32 count);

// Opportunity cost of the puyos a chain pops beyond 4 per link: what they would score as one more
// link at the end of the chain (the first link is the trigger and is never charged: the pair that
// fires usually lands its second puyo there)
i32 get_score_loss(const u8 popped[19], i32 count);

};

};