#pragma once

// The JSON line protocol of an engine: weight sets, fields and players as text, requests and replies.
// Included by pvp/main.cpp inside namespace pvp, like simulator.h.

// Loads the nested config.json into the 4 weight sets
void load_configs(search::Configs& configs, const std::string& path)
{
    std::ifstream file(path);

    if (!file.good()) {
        fprintf(stderr, "can't open \"%s\"\n", path.c_str());
        exit(1);
    }

    json js;
    file >> js;

    js.at("build").get_to(configs.build);
    js.at("freestyle").get_to(configs.freestyle);
    js.at("fast").get_to(configs.fast);
    js.at("ac").get_to(configs.ac);
};

// Field <-> 14 text rows (14th row first)
std::vector<std::string> field_to_rows(Field& field)
{
    std::vector<std::string> rows;

    std::string row14;

    for (i8 x = 0; x < 6; ++x) {
        row14 += ((field.row14 >> x) & 1) ? '#' : '.';
    }

    rows.push_back(row14);

    for (i8 y = 12; y >= 0; --y) {
        std::string row;

        for (i8 x = 0; x < 6; ++x) {
            row += cell::to_char(field.get_cell(x, y));
        }

        rows.push_back(row);
    }

    return rows;
};

Field field_from_rows(const std::vector<std::string>& rows)
{
    char c[13][7] = { 0 };

    for (i32 y = 0; y < 13; ++y) {
        for (i32 x = 0; x < 6; ++x) {
            c[y][x] = rows[y + 1][x];
        }

        c[y][6] = 0;
    }

    Field field;
    field.from(c);

    field.row14 = 0;

    for (i32 x = 0; x < 6; ++x) {
        if (rows[0][x] == '#') {
            field.row14 |= 1 << x;
        }
    }

    return field;
};

char direction_to_char(direction::Type r)
{
    switch (r)
    {
    case direction::Type::UP:
        return 'U';
    case direction::Type::RIGHT:
        return 'R';
    case direction::Type::DOWN:
        return 'D';
    case direction::Type::LEFT:
        return 'L';
    }

    return 'U';
};

direction::Type direction_from_char(char c)
{
    switch (c)
    {
    case 'U':
        return direction::Type::UP;
    case 'R':
        return direction::Type::RIGHT;
    case 'D':
        return direction::Type::DOWN;
    case 'L':
        return direction::Type::LEFT;
    }

    return direction::Type::UP;
};

json player_to_json(gaze::Player& player)
{
    json js;

    js["field"] = field_to_rows(player.field);

    std::vector<std::string> queue;

    for (auto& pair : player.queue) {
        queue.push_back(std::string() + cell::to_char(pair.first) + cell::to_char(pair.second));
    }

    js["queue"] = queue;
    js["all_clear"] = player.all_clear;
    js["bonus"] = player.bonus;
    js["attack"] = player.attack;
    js["attack_chain"] = player.attack_chain;
    js["attack_frame"] = player.attack_frame;
    js["dropping"] = player.dropping;

    return js;
};

gaze::Player player_from_json(const json& js)
{
    gaze::Player player;

    player.field = field_from_rows(js.at("field").get<std::vector<std::string>>());

    for (auto& pair : js.at("queue").get<std::vector<std::string>>()) {
        player.queue.push_back({ cell::from_char(pair[0]), cell::from_char(pair[1]) });
    }

    player.all_clear = js.at("all_clear").get<bool>();
    player.bonus = js.at("bonus").get<i32>();
    player.attack = js.at("attack").get<i32>();
    player.attack_chain = js.at("attack_chain").get<i32>();
    player.attack_frame = js.at("attack_frame").get<i32>();
    player.dropping = js.at("dropping").get<i32>();

    return player;
};

struct Request
{
    gaze::Player self;
    gaze::Player enemy;
    i32 target_point = TARGET_POINT;
    i32 trigger = ai::TRIGGER;
    bool stretch = true;
    // Beam search size. The defaults are the original constants; a smaller beam trades a little depth for speed.
    size_t beam_width = 250;
    size_t beam_depth = 16;
    size_t beam_target = 0;                      // chain score to rank candidates by reaching; 0 ranks by expected score
    bool beam_zoro = false;                      // sample same-color pairs into the future queues
    size_t attack_pairs = ai::QUEUE_VISIBLE;      // pairs the one-player attack search looks through
    bool reuse_search = false;
    size_t search_prefix = 0;                    // prefetch: the trailing guessed pair may change
    bool tactics_only = false;                  // defer an unprepared beam before the client releases DOWN
};

struct Reply
{
    move::Placement placement;
    i32 eval = 0;
    std::optional<i32> trigger = {};
    std::vector<move::Placement> alternatives;
    bool build_required = false;
    bool wait_for_enemy = false;
};

json request_to_json(Request& request)
{
    json js;

    js["self"] = player_to_json(request.self);
    js["enemy"] = player_to_json(request.enemy);
    js["target_point"] = request.target_point;
    js["trigger"] = request.trigger;
    js["stretch"] = request.stretch;
    js["beam_width"] = request.beam_width;
    js["beam_depth"] = request.beam_depth;
    js["attack_pairs"] = request.attack_pairs;

    return js;
};

Request request_from_json(const json& js)
{
    Request request;

    request.self = player_from_json(js.at("self"));
    request.enemy = player_from_json(js.at("enemy"));
    request.target_point = js.at("target_point").get<i32>();
    request.trigger = js.at("trigger").get<i32>();
    request.stretch = js.at("stretch").get<bool>();
    request.beam_width = js.value("beam_width", request.beam_width);
    request.beam_depth = js.value("beam_depth", request.beam_depth);
    request.beam_target = js.value("beam_target", request.beam_target);
    request.beam_zoro = js.value("beam_zoro", request.beam_zoro);
    request.attack_pairs = std::clamp(js.value("attack_pairs", request.attack_pairs), size_t(1), size_t(ai::QUEUE_VISIBLE));
    request.reuse_search = js.value("reuse_search", false);
    request.search_prefix = js.value("search_prefix", size_t(0));
    request.tactics_only = js.value("tactics_only", false);

    return request;
};

json reply_to_json(const Reply& reply)
{
    json js;

    js["x"] = reply.placement.x;
    js["r"] = std::string(1, direction_to_char(reply.placement.r));
    js["eval"] = reply.eval;
    js["wait_for_enemy"] = reply.wait_for_enemy;
    if (!reply.alternatives.empty()) {
        js["alternatives"] = json::array();
        for (auto& p : reply.alternatives) {
            js["alternatives"].push_back({{"x", p.x}, {"r", std::string(1, direction_to_char(p.r))}});
        }
    }

    if (reply.trigger.has_value()) {
        js["trigger"] = reply.trigger.value();
    }
    else {
        js["trigger"] = nullptr;
    }

    return js;
};

Reply reply_from_json(const json& js)
{
    Reply reply;

    reply.placement.x = js.at("x").get<i32>();
    reply.placement.r = direction_from_char(js.at("r").get<std::string>()[0]);
    reply.eval = js.at("eval").get<i32>();
    reply.wait_for_enemy = js.value("wait_for_enemy", false);

    if (!js.at("trigger").is_null()) {
        reply.trigger = js.at("trigger").get<i32>();
    }

    return reply;
};
