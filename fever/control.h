// Copied from fever-simulator src/control.h (MIT, same author): the offline piece controller ported from the
// Steam build 15209927 (docs/REVERSE_ENGINEERING.md there), matched frame by frame against the original
// routine. Keep it identical to that file apart from this note; change it there and copy it again.
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

// Port of the offline piece controller (FUN_140028010, vtable 0x1402acb48), its
// four control puyos, the pad layer (FUN_1400527f0) and the field queries the
// controller uses, for the Fever rule (flags 0x29c93: bit3 clear). The terrain is
// static (resting puyos at integer rows, size 1.0); see docs/REVERSE_ENGINEERING.md.
namespace control {

enum Button : uint8_t { LEFT = 1, RIGHT = 2, UP = 4, DOWN = 8, ROTATE_B = 0x10, ROTATE_A = 0x20 };
enum class Shape { PAIR, TRIPLE_L, TRIPLE_J, BIG, QUAD };

struct Pad {                      // FUN_140052710 / FUN_1400527f0
    // FUN_140052710 stores 0x3c0000 at +0x2c: the "previous" word starts as 0x3c.
    uint16_t held = 0, previous = 0x3c, repeat = 0, edge = 0;
    std::array<uint8_t,13> started{}, count{};
    void update(uint8_t buttons);
};

struct Body {                     // control puyo (vtable 0x1402acf20) or resting terrain
    float x = 0, y = 0;           // +0x28 / +0x2c
    float w = 1, h = 1;           // +0x40 / +0x44
    float backup_y = 0;           // +0x24
    int8_t cx = 0, cy = 0;        // +0x1e / +0x1f
    bool control = false;         // +0xe0 == 0
    bool solid = true;            // +0x104 (slot 0x220)
    int colour = 0;
};

struct Rules {
    uint32_t flags = 0x29c93;     // rule block 0x1402aa4e0
    // Pad seat: the base controller (vtable 0x1402ad2c0, PuyoOperateBase). Its slot 0x18
    // (FUN_14002a280) buffers rotation / movement while the field waits to spawn. The
    // CPU class (0x1402acb48, Com) replaces slot 0x18 with an empty function.
    bool pad_seat = false;
    float gravity = 10.0f/256.0f; // field +0x98 (level 5, FUN_1400496f0)
    int lock_frames = 32;         // field +0x208
    uint16_t speed_index = 0;     // rule +0x40 -> {1.0, 0.7, 0.5}
};

class Field {                     // field queries at slots 0x2e0/0x2e8/0x2f0/0x2f8/0x300/0x260/0x270
public:
    static constexpr int W = 8, H = 16, TOP = 3, LEFT = 1;
    struct Cell { int type = 0; Body* body = nullptr; };
    // 14 strings of 6 cells for game rows 1..14 (rows 1-2 are the 14th/13th rows,
    // the 12 visible rows are 3..14, 15 is the floor); '.' is empty.
    explicit Field(const std::vector<std::string>& visible = {});
    Field(const Field&) = delete;
    void assign(const Field& other);    // copy a field with no control puyos attached
    Cell& cell(int x, int y);
    bool blocked(const Body& p, int dx, int dy, float* gap) const;          // 0x2e8
    bool ground(const Body& p, float y, int dx, int dy) const;              // 0x2e0
    bool snap(Body& p, float* y) const;                                     // 0x2f0
    bool resting(const Body& p) const;                                      // 0x2f8
    void settle(Body& p) const;                                             // 0x300
    void attach(Body& p);                                                   // 0x260
    void detach(Body& p);                                                   // 0x270
    std::array<std::vector<Body*>,W> columns;
private:
    std::array<std::array<Cell,W>,H+2> cells{};                               // y in -1..16
    std::vector<Body> terrain;
    Cell& raw(int x, int y) const;
};

// Pad and controller input words survive from one piece to the next, and so do the
// pad seat's buffered rotation (+0x9a) and movement (+0x9b).
struct Carry { Pad pad; uint16_t held_prev = 0; int8_t rotate_buffer = 0, move_buffer = 0; };

struct State {                    // frame trace in the oracle's terms
    int x, y, rotation, angle, touch, ground;
    float fx, fy;
    bool locked;
    int colour;                   // +0xa8: the big puyo's current colour (first cell otherwise)
};

class Controller {
public:
    Controller(Field& field, Rules rules = {});
    // One spawn-wait frame (operate phase 1, FUN_14004d090): pad update then slot 0x18.
    // The phase spawns the piece in its last such frame; control starts the next frame.
    void wait(uint8_t buttons);
    // A frame in which the controller is not called (chains, other phases): pad only.
    void idle(uint8_t buttons) { pad.update(buttons); }
    void spawn(Shape shape, std::array<int,4> colours = {1,2,1,2});
    bool step(uint8_t buttons);   // pad update then slot 0x28; true when the piece locks
    State state() const;
    // Lock result: cell (x,y) of each control puyo in descriptor order.
    std::vector<std::pair<int,int>> cells() const;
    // Colour code (1..4 = R,G,B,Y) of each control puyo; a big puyo's change on rotation.
    std::vector<int> colours() const;
    int count() const { return n; }
    // Soft-drop points since spawn (score slot 0x40 with 1): one per row the held Down
    // crosses before the first touch, one for the lock that Down (or slot 0xe0) forces.
    int points() const { return drop_points; }
    Carry carry() const { return {pad,held_prev,rotate_buffer,move_buffer}; }
    void restore(const Carry& c) { pad = c.pad; held_prev = c.held_prev; rotate_buffer = c.rotate_buffer; move_buffer = c.move_buffer; }
private:
    Field& f; Rules r; Pad pad;
    std::array<Body,4> p{};
    std::array<float,8> old{};
    uint32_t shape = 0x200; int n = 2;
    float fx = 0, fy = 0, sx = 0, sy = 0, ddx = 0, ddy = 0, lift = 0, speed = 0, slide_step = 0, anim_y = 0;
    uint16_t input = 0, angle = 0, ground_frames = 0, rot_step = 0, next_input = 0, held_prev = 0;
    int rot = 0, locks = 0, drop_points = 0;
    uint8_t ax = 0, ay = 0, slide = 0, touch = 0, anim = 0, anim_idx = 0, quick = 0, scored = 0, registered = 0;
    uint8_t out = 0, snapped = 0, lift_count = 0;
    int8_t rotate_buffer = 0, move_buffer = 0;   // +0x9a / +0x9b
    bool active = false;
    bool touched = false;          // +0x124: set on the first touch, stops the row points
    bool bit(int b) const { return (r.flags >> b) & 1; }
    bool update();                 // FUN_140029e50
    bool frame();                  // FUN_140029b20
    void read_input();             // FUN_14002cd80
    void rotate_input();           // FUN_14002b190
    void quick_turn();             // FUN_14002afa0
    void rotate_anim();            // FUN_14002d1e0
    void lift_anim();              // FUN_14002d0e0
    void move();                   // FUN_140029540
    void fall();                   // FUN_14002a6e0
    bool land();                   // FUN_14002ab00
    void finalize();               // FUN_14002c800
    void rotate(int direction);    // FUN_14002c4b0
    void rotate_pair_cw(); void rotate_pair_ccw();     // 0x160 / 0x168
    void rotate_triple_cw(); void rotate_triple_ccw(); // 0x170 / 0x178
    void rotate_quad(bool cw);                         // 0x180 / 0x188
    bool can_move(int dx, int dy);                     // FUN_1400292e0
    bool ground_free(int i, int dx, int dy);           // FUN_14002c710 (slot 0x108)
    bool free(int i, int dx, int dy, float* gap);      // FUN_14002c7a0 (slot 0x110)
    bool lockable();                                   // FUN_14002c6c0
    void place();                                      // FUN_14002a350
    void align();                                      // FUN_14002cfd0
    void snap_after_move(int rows);                    // FUN_140029130
    void attach_all();                                 // FUN_14002c920
    void detach_all();                                 // FUN_14002cbc0
};


// One canonical per-frame input program and where it locked.
struct Route {
    std::vector<uint8_t> program;            // buttons per frame, the last frame locks
    std::vector<std::pair<int,int>> cells;   // game cells of each control puyo
    std::vector<int> colours;                // their colour codes (a big puyo's may change)
    Carry carry;                             // input state after the lock
    int points = 0;                          // soft-drop points (Controller::points)
};
// Rotation presses (none, A, B, AA, BB) and horizontal taps (-5..+5): concurrent (with
// or without DOWN), rotation first, movement first, or climbing (a rotation before each
// step); one press per two frames, then DOWN held. Reachability is a lower bound.
// delay: frames with no button before each program (a controller that starts late, as
// the bridge does: its first press can land on control frame 1 at the earliest).
std::vector<Route> explore(const std::vector<std::string>& rows, Shape shape, const Carry& carry,
                           int limit = 600, Rules rules = {}, std::array<int,4> colours = {1,2,1,2},
                           int delay = 0);

}
