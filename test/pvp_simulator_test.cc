#define main ama_pvp_main
#include "../pvp/main.cpp"
#undef main
#include <random>

using namespace pvp;

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

struct FixedEngine : Engine
{
    move::Placement goal = {2, direction::Type::UP};
    std::vector<Request> requests;
    Reply think(Request& request) override { requests.push_back(request); return Reply{.placement = goal}; }
    std::string name() override { return "fixed"; }
};

std::vector<json> events(const std::ostringstream& stream)
{
    std::istringstream input(stream.str());
    std::vector<json> rows;
    std::string line;
    while (std::getline(input, line)) rows.push_back(json::parse(line));
    return rows;
}

int main()
{
    Timing timing;
    Field empty;
    require(timing.placement_frames(empty, {2, direction::Type::UP}) == 22, "empty field soft drop");
    require(timing.placement_frames(empty, {2, direction::Type::UP}, {cell::Type::RED, cell::Type::RED}) == 20, "same-color half turn is faster");
    require(timing.to_ai(0) == 0 && timing.to_ai(1) == 1 && timing.to_ai(82) == 2, "frame to AI conversion");
    Field raised;
    for (i32 i = 0; i < 5; ++i) raised.drop_puyo(2, cell::Type::GARBAGE);
    require(timing.placement_frames(raised, {2, direction::Type::UP}) == 12, "stack height affects drop time");
    require(timing.placement_frames(raised, {2, direction::Type::RIGHT}) > 22, "tear distance adds time");
    std::mt19937 random(123);
    for (i32 sample = 0; sample < 300; ++sample) {
        Field f;
        for (i8 x = 0; x < 6; ++x) {
            i32 height = random() % 12;
            for (i32 y = 0; y < height; ++y) f.drop_puyo(x, cell::Type(random() % 5));
        }
        auto original = f;
        auto masks = original.pop();
        auto expected = chain::get_score(masks);
        auto links = resolve_timed_chain(f, timing);
        i32 score = 0;
        for (auto link : links) { score += link.score; require(link.frames >= timing.vanish, "positive link time"); }
        require(f == original && score == expected.score && i32(links.size()) == expected.count, "timed chain agrees with core");
    }
    for (i32 count = 1; count <= 30; ++count) {
        Field f, repeated;
        u32 rng = 123, same = 123;
        drop_match_garbage(f, count, rng); drop_match_garbage(repeated, count, same);
        require(i32(f.get_count()) == count && f == repeated, "garbage conserves count and seed");
        for (i8 x = 0; x < 6; ++x) require(f.get_height(x) >= count / 6 && f.get_height(x) <= (count + 5) / 6, "garbage distribution");
    }
    Options options;
    options.max_moves = 1; options.log = "memory";
    FixedEngine a, b;
    Engine* engines[2] = {&a, &b};
    std::ostringstream log;
    auto game = play_frames(engines, 1, 0, options, log, {}, {{cell::Type::RED, cell::Type::BLUE}});
    require(game.winner == -1 && game.reason == "max_moves" && game.moves[0] == 1 && game.moves[1] == 1, "symmetric cap");
    require(a.requests[0].enemy.field.is_empty() && b.requests[0].enemy.field.is_empty(), "simultaneous decision views");
    auto rows = events(log);
    require(rows[0]["frame"] == 11 && rows[0]["lock_frame"] == 33, "decision before actual lock");

    std::array<FramePlayer, 2> start;
    for (auto& player : start) for (i32 i = 0; i < 10; ++i) player.field.drop_puyo(2, cell::Type(i % 4));
    log.str(""); a.requests.clear(); b.requests.clear();
    game = play_frames(engines, 1, 1, options, log, start, {{cell::Type::RED, cell::Type::BLUE}});
    if (!(game.winner == -1 && game.reason == "death" && game.ticks == 13))
        fprintf(stderr, "death result: winner=%d reason=%s frames=%d\n", game.winner, game.reason.c_str(), game.ticks);
    require(game.winner == -1 && game.reason == "death" && game.ticks == 13, "simultaneous deaths are a draw");

    start = {};
    for (auto& player : start) {
        for (i32 i = 0; i < 3; ++i) player.field.drop_puyo(0, cell::Type::RED);
        player.all_clear = true;
    }
    a.goal = b.goal = {0, direction::Type::UP};
    log.str(""); a.requests.clear(); b.requests.clear();
    game = play_frames(engines, 1, 0, options, log, start, {{cell::Type::RED, cell::Type::BLUE}});
    require(game.sent[0] == 0 && game.sent[1] == 0 && game.reason == "max_moves", "simultaneous all clear attacks offset");
    require(a.requests[0].enemy.attack == 0 && b.requests[0].enemy.attack == 0, "no attacks from future decisions");

    start = {};
    for (i32 i = 0; i < 3; ++i) start[0].field.drop_puyo(0, cell::Type::RED);
    start[0].all_clear = true;
    a.goal = {0, direction::Type::UP}; b.goal = {5, direction::Type::UP};
    options.max_moves = 3;
    log.str(""); a.requests.clear(); b.requests.clear();
    game = play_frames(engines, 1, 0, options, log, start, {{cell::Type::RED, cell::Type::BLUE}});
    bool saw_attack = false, saw_garbage = false;
    for (auto& row : events(log)) {
        if (row["event"] == "decision" && row["player"] == "B" && row["enemy_attack_frames"] > 0) {
            saw_attack = true;
            require(row["enemy"]["attack_frame"] == timing.to_ai(row["enemy_attack_frames"]), "request keeps abstract attack units");
        }
        if (row["event"] == "garbage") {
            saw_garbage = true;
            require(row["frame"] >= 111, "garbage waits for sender chain end");
        }
    }
    require(saw_attack && saw_garbage, "running chain and garbage events exercised");
    require(game.moves[0] <= 3 && game.moves[1] <= 3, "unequal speeds respect per-player cap");
    require(!valid_placement(empty, {-1, direction::Type::UP}) && !valid_placement(empty, {5, direction::Type::RIGHT}), "invalid placement rejected before indexing");
    printf("pvp simulator checks passed\n");
}
