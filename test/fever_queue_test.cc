#include "../core/fever_queue.h"
#include <cstdio>
#include <stdexcept>
#include <string>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

std::string text(const fever::Queue& queue)
{
    std::string result;
    for (const auto& value : queue) {
        if (!result.empty()) result += ' ';
        result += "2340"[usize(value.shape)];
        result += ':';
        for (usize i = 0; i < piece::color_count(value.shape); ++i) result += cell::to_char(value.colors[i]);
    }
    return result;
}

// Shape, validity and the color layout each cycle symbol promises.
void check(const dropset::Character& character, const fever::Queue& queue, u64 start)
{
    for (usize i = 0; i < queue.size(); ++i) {
        const auto drop = dropset::drop_at(character, start + i);
        const auto& c = queue[i].colors;
        require(drop && queue[i].shape == dropset::shape_of(*drop), "shape differs from cycle");
        require(piece::is_valid(queue[i]), "invalid piece generated");
        if (*drop == dropset::Drop::TRIPLE_VERTICAL) require(c[0] == c[1], "vertical triple layout");
        if (*drop == dropset::Drop::TRIPLE_HORIZONTAL) require(c[0] == c[2], "horizontal triple layout");
        if (*drop == dropset::Drop::QUAD) require(c[0] == c[1] && c[2] == c[3] && c[0] != c[2], "quad layout");
    }
}
}

int main()
{
    using cell::Type;
    using dropset::Drop;
    constexpr auto R = Type::RED, Y = Type::YELLOW, N = Type::NONE;

    // make_piece never guesses
    require(!fever::make_piece(Drop::TRIPLE_UNKNOWN, R, Y), "unknown triple guessed");
    require(!fever::make_piece(Drop::QUAD, R, R), "single-color quad");
    require(!fever::make_piece(Drop::PAIR, R, N) && !fever::make_piece(Drop::PAIR, Type::GARBAGE, R), "non-color pair");
    require(!fever::make_piece(Drop::BIG, N, N), "non-color big");
    require(fever::make_piece(Drop::BIG, R, Y) == piece::Piece{ piece::Shape::BIG, { R, N, N, N } }, "big keeps one color");
    require(fever::make_piece(Drop::TRIPLE_VERTICAL, R, R).has_value(), "same-color triple rejected");
    require(!fever::create_queue("nobody", 1, 16), "unknown id produced a queue");
    const dropset::Character unknown{ "x", "", "", dropset::Status::UNKNOWN };
    const dropset::Character legacy{ "y", "", "2232232*2322322*", dropset::Status::PLAYER };
    require(!fever::create_queue(unknown, 1, 16) && !fever::create_queue_virtual(unknown, 0, 16, 0), "unknown cycle");
    require(!fever::create_queue(legacy, 1, 16) && !fever::create_queue_virtual(legacy, 0, 16, 0), "legacy triple guessed");
    require(fever::create_queue(legacy, 1, 2).has_value(), "legacy pairs before the first triple");

    usize checks = 0;
    for (const auto& character : dropset::characters()) {
        require(!fever::create_queue_virtual(character, -1, 16, 0), "bag id below range");
        require(!fever::create_queue_virtual(character, fever::VIRTUAL_COUNT, 16, 0), "bag id above range");
        require(fever::create_queue(character, 1, 0)->empty(), "empty queue");

        for (u64 seed : { u64(0), u64(1), u64(2), u64(12345), ~u64(0) }) {
            for (u64 start : { u64(0), u64(5), u64(16), u64(37) }) {
                const auto queue = fever::create_queue(character, seed, 64, start);
                require(queue && queue->size() == 64, "queue length");
                require(queue == fever::create_queue(character.id, seed, 64, start), "not deterministic");
                check(character, *queue, start);
                // A shorter request is a prefix: colors never depend on the count.
                const auto prefix = fever::create_queue(character, seed, 20, start);
                require(prefix && std::equal(prefix->begin(), prefix->end(), queue->begin()), "prefix changed");
                std::printf("real\t%s\t%llu\t%llu\t%s\n", character.id.data(), (unsigned long long)seed,
                            (unsigned long long)start, text(*queue).c_str());
                ++checks;
            }
        }
        require(fever::create_queue(character, 1, 64) != fever::create_queue(character, 2, 64), "seed ignored");

        for (i32 id = 0; id < fever::VIRTUAL_COUNT; ++id) {
            for (u64 start : { u64(0), u64(3), u64(21) }) {
                const auto queue = fever::create_queue_virtual(character, id, 40, start);
                require(queue && queue->size() == 40, "virtual queue length");
                require(queue == fever::create_queue_virtual(character, id, 40, start), "virtual not deterministic");
                check(character, *queue, start);
                std::printf("virtual\t%s\t%d\t%llu\t%s\n", character.id.data(), id,
                            (unsigned long long)start, text(*queue).c_str());
                ++checks;
            }
        }
    }

    // Arle's virtual queues are the Tsu search's pair bags.
    const auto arle = fever::create_queue_virtual(*dropset::find("arle"), 3, 4, 0);
    require(text(*arle) == "2:YG 2:RB 2:YG 2:RB", "arle virtual queue differs from the pair bags");

    std::fprintf(stderr, "%llu checks passed\n", (unsigned long long)checks);
    return 0;
}
