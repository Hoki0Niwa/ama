#pragma once
#include "../core/core.h"
#include "../core/operation.h"
#include <array>

namespace fever::normal_space {
// Match generated pair/triple locks to the executable spawn route.
inline auto moves(Field field, const piece::Piece& piece, const rule::Rule& rules) {
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
    u64 key=(u64(pair)<<24)|(u64(same)<<25);
    for (int x=0;x<6;++x) key|=u64(heights[x])<<(4*x);
    // POD storage avoids MinGW's thread-local dynamic destructor registration
    // across inline call sites when virtual-queue worker threads are recreated.
    struct Cached { u64 key=0; u32 mask=0; bool used=false; };
    thread_local std::array<Cached,2048> cache{};
    auto& cached=cache[(key*11400714819323198485ull)>>53];
    u32 mask=0;
    if (cached.used && cached.key==key) mask=cached.mask;
    else {
        for (int x=0;x<(pair ? 6 : 5);++x) for (int r=0;r<4;++r) {
            auto geometry=piece::geometry(piece,direction::Type(r));
            if (operation::route(heights,pair ? 2 : 3,{2,0,0},x+geometry->pivot_x,r,same,true,true))
                mask|=u32(1)<<(4*x+r);
        }
        cached={key,mask,true};
    }
    decltype(result) executable;
    for (int i=0;i<result.get_size();++i)
        if (mask&(u32(1)<<(4*result[i].x+int(result[i].r)))) executable.add(result[i]);
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
