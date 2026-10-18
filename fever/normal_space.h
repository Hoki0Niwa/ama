#pragma once
#include "../core/core.h"
#include "../core/operation.h"
#include "control_moves.h"
#include <array>

namespace fever::normal_space {
// Spawn-row lifts: goals the route model reaches only with the suspended lift (fever/operation_suspensions.h).
// The game's own controller locks most of them by another order of presses, with a program the bridge runs
// (fever/control_moves.h; 2026-10-18: 91 of the 100 logged failures).
inline u32 lifted_goals(const int heights[6], const piece::Piece& piece, u32 routed, bool same) {
    u32 lifted=0;
    operation::SpawnRowLifts enable;
    for (int x=0;x<5;++x) for (int r=0;r<4;++r) {
        if (routed>>(4*x+r)&1) continue;
        auto geometry=piece::geometry(piece,direction::Type(r));
        if (operation::route(heights,3,{2,0,0},x+geometry->pivot_x,r,same,true,true)) lifted|=u32(1)<<(4*x+r);
    }
    return lifted;
}
// Match generated pair/triple locks to the executable spawn route.
// current: the piece about to be placed (a decision's root, the `placements` answer). Only for it are spawn-row
// lifts the game's controller locks added (below): they are a way to execute this move, and exploring costs a
// millisecond or more, which deep in a search on high boards slowed decisions enough for pieces to fall
// unsteered (2026-10-18 live run: right after nuisance landed).
inline auto moves(Field field, const piece::Piece& piece, const rule::Rule& rules, bool current = false) {
    auto result = move::generate(field, piece, rules);
    if (!rules.special_moves || (piece.shape != piece::Shape::PAIR && piece.shape != piece::Shape::TRIPLE)) return result;
    // Pair generation already uses the same operation::reachable graph as
    // the live route, including timed clearance. Repeating a shortest-path
    // search for all 24 goals adds no pair candidates or validation. Triples
    // still need the filter for the measured, generator-only extensions.
    if (piece.shape == piece::Shape::PAIR) return result;
    u8 h[6]; field.get_heights(h); int heights[6];
    for (int x=0;x<6;++x) heights[x]=h[x];
    const bool pair=piece.shape==piece::Shape::PAIR;
    const bool same=pair && piece.colors[0]==piece.colors[1];
    // Which cells share a colour decides which labels lock the same board (control_moves maps outcomes to labels).
    const u64 pattern=(u64(piece.colors[0]==piece.colors[1])<<26)|(u64(piece.colors[0]==piece.colors[2])<<27)|(u64(piece.colors[1]==piece.colors[2])<<28);
    u64 key=(u64(pair)<<24)|(u64(same)<<25)|pattern|(u64(operation::measured_lift_generation()&0xffffu)<<32);
    for (int x=0;x<6;++x) key|=u64(heights[x])<<(4*x);
    // POD storage avoids MinGW's thread-local dynamic destructor registration
    // across inline call sites when virtual-queue worker threads are recreated.
    struct Cached { u64 key=0; u32 mask=0; u32 controlled=0; bool used=false; bool explored=false; };
    thread_local std::array<Cached,2048> cache{};
    auto& cached=cache[(key*11400714819323198485ull)>>53];
    u32 mask=0, controlled=0;
    if (cached.used && cached.key==key) { mask=cached.mask; controlled=cached.controlled; }
    else {
        cached={key,0,0,true,false};
        for (int x=0;x<(pair ? 6 : 5);++x) for (int r=0;r<4;++r) {
            auto geometry=piece::geometry(piece,direction::Type(r));
            const int pivot=x+geometry->pivot_x;
            bool executable=operation::route(heights,pair ? 2 : 3,{2,0,0},pivot,r,same,true,true).has_value();
            if (!executable && !pair && operation::has_measured_lifts() && operation::measured_lift_allowed(heights,pivot,r)) {
                operation::SpawnRowLifts enable;
                executable=operation::route(heights,3,{2,0,0},pivot,r,same,true,true).has_value();
            }
            if (executable) mask|=u32(1)<<(4*x+r);
        }
        cached.mask=mask;
    }
    if (current && !cached.explored) {
        const u32 lifted=lifted_goals(heights,piece,mask,same);
        if (lifted) controlled=control_moves::triple_mask(field,piece,rules)&lifted;
        cached.controlled=controlled; cached.explored=true;
    }
    if (!current) controlled=0;
    decltype(result) executable;
    for (int i=0;i<result.get_size();++i)
        if (mask&(u32(1)<<(4*result[i].x+int(result[i].r)))) executable.add(result[i]);
    for (int bit=0;bit<20;++bit) if (controlled>>bit&1)
        executable.add({i8(bit/4),direction::Type(bit%4)});
    return executable;
}
// Apply to settled boards after clearing, never to an intermediate lock pose.
inline bool upper_open(Field field) {
    return true; // Row 13 is legal; rely on physical placement and central death rows.
}
inline bool room(Field field, int margin) {
    return !field.is_dead(rule::FEVER) && upper_open(field)
        && field.get_height(2) <= 11 - margin && field.get_height(3) <= 11 - margin;
}
template<class Moves>
inline bool has_open_move(Field field, const piece::Piece& piece, Moves& moves, const rule::Rule& rules) {
    for (int i = 0; i < moves.get_size(); ++i) {
        auto board = field;
        if (!board.drop_piece(moves[i].x, moves[i].r, piece, rules)) continue;
        board.pop();
        u8 heights[6]; board.get_heights(heights);
        if (!board.is_dead(rules) && !rule::is_unsafe(heights, rules) && upper_open(board)) return true;
    }
    return false;
}
}
