#pragma once
#include "../core/core.h"
#include "../core/operation.h"
#include "control_moves.h"
#include <array>
#include <cstdlib>
#include <string_view>

namespace fever::normal_space {
// Goals the route model cannot take: its turns next to tall columns are not the game's (2026-10-14: every stopped
// `hook` and high sideways kick turned out a push the port reproduces to the frame). The game's own controller locks
// them with a program the bridge runs (fever/control_moves.h). AMA_NO_CONTROLLER_PROGRAMS=1 offers none.
inline bool controller_goals_off() {
    static const bool off = [] { const char* v = std::getenv("AMA_NO_CONTROLLER_PROGRAMS"); return v && *v && std::string_view(v) != "0"; }();
    return off;
}
// Match generated pair/triple locks to the executable spawn route.
// current: the piece about to be placed (a decision's root, the `placements` answer). Only for it are the goals
// the game's controller locks added (below): they are a way to execute this move, and exploring costs a few
// milliseconds, which deep in a search on high boards slowed decisions enough for pieces to fall unsteered
// (2026-10-18 live run: right after nuisance landed).
inline auto moves(Field field, const piece::Piece& piece, const rule::Rule& rules, bool current = false) {
    auto result = move::generate(field, piece, rules);
    if (!rules.special_moves || (piece.shape != piece::Shape::PAIR && piece.shape != piece::Shape::TRIPLE)) return result;
    // Pair generation already uses the same operation::reachable graph as
    // the live route, including timed clearance. Repeating a shortest-path
    // search for all 24 goals adds no pair candidates or validation. Triples
    // still need the filter for the measured, generator-only extensions.
    const bool pair=piece.shape==piece::Shape::PAIR;
    if (pair && !current) return result;
    u8 h[6]; field.get_heights(h); int heights[6];
    for (int x=0;x<6;++x) heights[x]=h[x];
    const bool same=pair && piece.colors[0]==piece.colors[1];
    // Which cells share a colour decides which labels lock the same board (control_moves maps outcomes to labels).
    const u64 pattern=pair ? 0 : (u64(piece.colors[0]==piece.colors[1])<<26)|(u64(piece.colors[0]==piece.colors[2])<<27)|(u64(piece.colors[1]==piece.colors[2])<<28);
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
        if (pair) for (int i=0;i<result.get_size();++i) {
            const int x=result[i].x, r=int(result[i].r);
            mask|=u32(1)<<(4*x+r);
            // A pair of one color lies the same either way round (move::generate lists one of the two).
            if (same && r==0) mask|=u32(1)<<(4*x+2);
            if (same && r==1) mask|=u32(1)<<(4*(x+1)+3);
        }
        else for (int x=0;x<5;++x) for (int r=0;r<4;++r) {
            auto geometry=piece::geometry(piece,direction::Type(r));
            const int pivot=x+geometry->pivot_x;
            bool executable=operation::route(heights,3,{2,0,0},pivot,r,same,true,true).has_value();
            if (!executable && operation::has_measured_lifts() && operation::measured_lift_allowed(heights,pivot,r)) {
                operation::SpawnRowLifts enable;
                executable=operation::route(heights,3,{2,0,0},pivot,r,same,true,true).has_value();
            }
            if (executable) mask|=u32(1)<<(4*x+r);
        }
        cached.mask=mask;
    }
    if (current && !cached.explored) {
        // Every label a piece can have: x 0-4 for a triple's box; a pair's axis 0-5, its child inside the board.
        const u32 goals=pair ? 0xffffffu&~(u32(1)<<3)&~(u32(1)<<21) : 0xfffffu;
        if ((goals&~mask) && !field.is_dead(rules) && !controller_goals_off())
            controlled=control_moves::triple_mask(field,piece,rules)&goals&~mask;
        cached.controlled=controlled; cached.explored=true;
    }
    if (!current) controlled=0;
    decltype(result) executable;
    if (pair) executable=result;
    else for (int i=0;i<result.get_size();++i)
        if (mask&(u32(1)<<(4*result[i].x+int(result[i].r)))) executable.add(result[i]);
    for (int bit=0;bit<(pair ? 24 : 20);++bit) if (controlled>>bit&1) {
        // One label for a pair of one color: up and right stand for down and left, as in move::generate.
        if (same && bit%4==2 && (controlled>>(bit-2)&1)) continue;
        if (same && bit%4==3 && bit>=6 && (controlled>>(bit-6)&1)) continue;
        executable.add({i8(bit/4),direction::Type(bit%4)});
    }
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
