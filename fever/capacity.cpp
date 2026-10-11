#include "capacity.h"
#include "normal_space.h"
#include "text.h"
#include <stdexcept>

namespace fever {
json inspect_capacity(Field field, const Queue& queue, const rule::Rule& rules,
                      const normal_scoring::Entry* normal, int target) {
    if (queue.empty()) throw std::invalid_argument("visible queue required");
    auto moves = normal_space::moves(field, queue.front(), rules);
    auto now = fire::best_now(field, queue.front(), rules, normal);
    const int current = now ? now->chain.count : 0;
    const int points = now ? now->chain.score : 0;
    auto available = fire::best_visible(field, queue, rules, normal);
    const int available_chain = available ? available->chain.count : 0;
    const int available_score = available ? available->chain.score : 0;
    int safe = 0, improving = 0, retained = 0, next_chain = 0;
    json extensions = json::array();
    Queue tail(queue.begin()+1, queue.end());
    for (int i=0;i<moves.get_size();++i) {
        auto board=field;
        auto placed=board.drop_piece(moves[i].x,moves[i].r,queue.front(),rules);
        if (!placed || placed->discarded) continue;
        const int cleared = board.pop().get_size();
        if (cleared > 2 || !normal_space::room(board,rules.margin)) continue;
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
    // A high count is pressure, not loss of space. Continue a visible improvement;
    // do not cover the only executable main merely because one quiet lock fits.
    const bool release=safe==0 || (crowded && available_chain>2 && improving==0);
    return {{"release",release},{"crowded",crowded},{"safe_moves",safe},
        {"current_chain",current},{"current_score",points},{"visible_extension_chain",next_chain},
        {"available_chain",available_chain},{"available_score",available_score},
        {"available_x",available ? available->placement.x : 0},
        {"available_r",std::string(1,available ? text::from_direction(available->placement.r) : 'U')},
        {"available_moves",available ? available->moves : 0},
        {"retaining_moves",retained},{"improving_moves",improving},{"extensions",extensions},
        {"reason",safe==0 ? "no_safe_stack" : release ? "no_main_retaining_continuation" : improving ? "visible_growth" : "space_remains"}};
}
}
