#include "capacity.h"
#include "normal_space.h"
#include "text.h"
#include <stdexcept>

namespace fever {
json inspect_capacity(Field field, const Queue& queue, const rule::Rule& rules,
                      const normal_scoring::Entry* normal, int target, bool threat) {
    if (queue.empty()) throw std::invalid_argument("visible queue required");
    auto moves = normal_space::moves(field, queue.front(), rules);
    auto now = fire::best_now(field, queue.front(), rules, normal);
    const int current = now ? now->chain.count : 0;
    const int points = now ? now->chain.score : 0;
    auto available = fire::best_visible(field, queue, rules, normal);
    const int available_chain = available ? available->chain.count : 0;
    const int available_score = available ? available->chain.score : 0;
    int safe = 0, survivable = 0, improving = 0, retained = 0, next_chain = 0;
    json extensions = json::array();
    Queue tail(queue.begin()+1, queue.end());
    for (int i=0;i<moves.get_size();++i) {
        auto board=field;
        auto placed=board.drop_piece(moves[i].x,moves[i].r,queue.front(),rules);
        if (!placed || placed->discarded) continue;
        const int cleared = board.pop().get_size();
        if (!normal_space::room(board,rules.margin)) continue;
        // A natural clear that leaves room is a way to go on living, not a
        // lack of space: it must not be mistaken for having no stack at all.
        ++survivable;
        if (cleared > 2) continue;
        ++safe;
        auto visible=fire::best_visible(board,tail,rules,normal);
        const int links=visible ? visible->chain.count : 0;
        const int score=visible ? visible->chain.score : 0;
        next_chain=std::max(next_chain,links);
        const bool holds=available_chain <= 2 || (links>=available_chain && score>=available_score);
        // A small visible improvement is not a reason to abandon the large
        // main objective. Only a near-target executable extension defers panic.
        const bool grows=holds && links>=std::max(4,target-1) && (links>current || score>points);
        retained+=holds; improving+=grows;
        extensions.push_back({{"x",moves[i].x},{"r",std::string(1,text::from_direction(moves[i].r))},
            {"chain",links},{"score",score},{"cleared",cleared},{"retains",holds},{"improves",grows}});
    }
    const int capacity=4*13+2*(11-rules.margin);
    const bool crowded=int(field.get_count())+int(piece::cell_count(queue.front().shape))>=capacity;
    // A main worth protecting: near the target, not just any visible clear.
    const int floor_chain=std::max(4,target-5);
    const bool substantial=available_chain>=floor_chain;
    // A high count is pressure, not loss of space. Continue a visible improvement;
    // do not cover the only executable main merely because one quiet lock fits.
    // Firing a small visible clear is the last resort: while any placement
    // survives, only a real main is cashed in, and a small one is shaved.
    const bool nothing_survives=survivable==0;
    const bool no_quiet_main=safe==0 && substantial;
    // Under attack, every quiet continuation that fits would break a main this
    // large and none grows it, and what is left absorbs no more than the
    // visible pieces: stacking on only buries the chain until a drop kills the
    // board. Without a threat the main is held to the last moment.
    const bool scarce=safe<=int(queue.size())+1;
    const bool unretained_main=threat && substantial && scarce && retained==0 && improving==0;
    const bool pressed=crowded && available_chain>2 && improving==0;
    const bool release=nothing_survives || no_quiet_main || unretained_main || pressed;
    const char* reason=nothing_survives ? "no_safe_stack"
        : no_quiet_main ? "no_quiet_main_continuation"
        : unretained_main ? "unretained_main"
        : pressed ? "no_main_retaining_continuation"
        : improving ? "visible_growth"
        : safe==0 ? "natural_clear_continues" : "space_remains";
    return {{"release",release},{"crowded",crowded},{"safe_moves",safe},
        {"current_chain",current},{"current_score",points},{"visible_extension_chain",next_chain},
        {"available_chain",available_chain},{"available_score",available_score},
        {"available_x",available ? available->placement.x : 0},
        {"available_r",std::string(1,available ? text::from_direction(available->placement.r) : 'U')},
        {"available_moves",available ? available->moves : 0},
        {"retaining_moves",retained},{"improving_moves",improving},{"extensions",extensions},
        {"survivable_moves",survivable},{"threat",threat},{"main_floor",floor_chain},{"reason",reason}};
}
}
