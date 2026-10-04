// Internal benchmark for the current common Ama core on the Fever development branch.
// This is not the Tsu bridge engine protocol or a Fever game client.
#include "../core/core.h"
#include "../ai/search/beam/beam.h"

static json show(Field field)
{
    json rows = json::array();
    std::string top(6, '.');
    for (int x = 0; x < 6; ++x) if (field.row14 & (1 << x)) top[x] = '#';
    rows.push_back(top);
    for (int y = 12; y >= 0; --y) {
        std::string row;
        for (int x = 0; x < 6; ++x) row += cell::to_char(field.get_cell(x, y));
        rows.push_back(row);
    }
    return rows;
}

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    std::ifstream input(argv[1]);
    json config;
    input >> config;
    auto weights = config.at("build").get<beam::eval::Weight>();
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            auto request = json::parse(line);
            Field field;
            auto rows = request.at("field").get<std::vector<std::string>>();
            if (rows.size() != 14) throw std::runtime_error("14 rows required");
            for (int row = 0; row < 14; ++row) {
                if (rows[row].size() != 6) throw std::runtime_error("6 columns required");
                for (int x = 0; x < 6; ++x) {
                    if (rows[row][x] == '.') continue;
                    if (row == 0) field.row14 |= 1 << x;
                    else field.set_cell(x, 13 - row, cell::from_char(rows[row][x]));
                }
            }
            cell::Queue queue;
            for (const auto& text : request.at("queue")) {
                auto pair = text.get<std::string>();
                if (pair.size() != 2) throw std::runtime_error("two cells required");
                queue.emplace_back(cell::from_char(pair[0]), cell::from_char(pair[1]));
            }
            beam::Configs settings;
            settings.width = request.value("width", settings.width);
            settings.depth = request.value("depth", settings.depth);
            if (queue.size() < 2 || queue.size() > settings.depth) throw std::runtime_error("invalid queue depth");
            const auto start = std::chrono::steady_clock::now();
            beam::node::Data node { .field = field, .score = {0, 0}, .index = 0 };
            beam::eval::evaluate(node, weights);
            auto result = beam::search_multi(field, queue, weights, settings);
            const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            json reply = { {"search_ms", ms}, {"eval", node.score.eval} };
            if (!result.candidates.empty()) {
                auto chosen = result.candidates.front();
                auto after = field;
                after.drop_pair(chosen.placement.x, chosen.placement.r, queue[0]);
                auto masks = after.pop();
                auto score = chain::get_score(masks);
                reply["chosen"] = {{"x", chosen.placement.x}, {"r", int(chosen.placement.r)},
                    {"expected_score", chosen.score}, {"chain", score.count}, {"score", score.score},
                    {"next_field", show(after)}};
            }
            std::sort(result.candidates.begin(), result.candidates.end(), [](const auto& a, const auto& b) {
                if (a.placement.x != b.placement.x) return a.placement.x < b.placement.x;
                return a.placement.r < b.placement.r;
            });
            reply["candidates"] = json::array();
            for (const auto& candidate : result.candidates)
                reply["candidates"].push_back({{"x", candidate.placement.x},
                    {"r", int(candidate.placement.r)}, {"score", candidate.score}});
            std::cout << reply.dump() << std::endl;
        } catch (const std::exception& error) {
            std::cout << json({{"error", error.what()}}).dump() << std::endl;
        }
    }
}
