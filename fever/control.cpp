// Copied from fever-simulator src/control.cpp (MIT, same author): the offline piece controller ported from the
// Steam build 15209927 (docs/REVERSE_ENGINEERING.md there), matched frame by frame against the original
// routine. Keep it identical to that file apart from this note; change it there and copy it again.
#include "control.h"
#include <bit>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace control {
namespace {
// DAT_1402ad4d0: (dx,dy) of the four control puyos per rotation (y grows downwards).
constexpr int8_t OFFS[4][4][2] = {
    {{0,0},{0,-1},{1,0},{1,-1}}, {{0,0},{1,0},{0,1},{1,1}},
    {{0,0},{0,1},{-1,0},{-1,1}}, {{0,0},{-1,0},{0,-1},{-1,-1}}};
// DAT_1402ad4f0: 1-based processing order per rotation (bottom first).
constexpr uint8_t ORDER[4][4] = {{1,3,2,4},{3,4,1,2},{4,2,3,1},{2,1,4,3}};
constexpr uint16_t ANGLE[4] = {0,0x4000,0x8000,0xc000};          // DAT_1402ad4a8
constexpr int8_t QUAD_CW[4][2] = {{0,-1},{1,0},{0,1},{-1,0}};     // DAT_1402ad4b0
constexpr int8_t QUAD_CCW[4][2] = {{1,0},{0,1},{-1,0},{0,-1}};    // DAT_1402ad4b8
// fx_trig table at 0x14031a9f0 sampled every 0x800: {sin, cos} bit patterns.
constexpr uint32_t TRIG[32][2] = {
    {0x00000000u,0x3f800000u},{0x3e47ae14u,0x3f7b22d1u},{0x3ec41893u,0x3f6c8b44u},{0x3f0e5604u,0x3f54fdf4u},
    {0x3f34fdf4u,0x3f34fdf4u},{0x3f54fdf4u,0x3f0e5604u},{0x3f6c8b44u,0x3ec41893u},{0x3f7b22d1u,0x3e47ae14u},
    {0x3f800000u,0x00000000u},{0x3f7b22d1u,0xbe47ae14u},{0x3f6c8b44u,0xbec41893u},{0x3f54fdf4u,0xbf0e5604u},
    {0x3f34fdf4u,0xbf34fdf4u},{0x3f0e5604u,0xbf54fdf4u},{0x3ec41893u,0xbf6c8b44u},{0x3e47ae14u,0xbf7b22d1u},
    {0x00000000u,0xbf800000u},{0xbe47ae14u,0xbf7b22d1u},{0xbec41893u,0xbf6c8b44u},{0xbf0e5604u,0xbf54fdf4u},
    {0xbf34fdf4u,0xbf34fdf4u},{0xbf54fdf4u,0xbf0e5604u},{0xbf6c8b44u,0xbec41893u},{0xbf7b22d1u,0xbe47ae14u},
    {0xbf800000u,0x00000000u},{0xbf7b22d1u,0x3e47ae14u},{0xbf6c8b44u,0x3ec41893u},{0xbf54fdf4u,0x3f0e5604u},
    {0xbf34fdf4u,0x3f34fdf4u},{0xbf0e5604u,0x3f54fdf4u},{0xbec41893u,0x3f6c8b44u},{0xbe47ae14u,0x3f7b22d1u}};
float trig(uint16_t angle, int k) {
    if (angle & 0x7ff) throw std::logic_error("control angle off the 0x800 grid");
    return std::bit_cast<float>(TRIG[angle >> 11][k]);
}
float sine(uint16_t a) { return trig(a,0); }    // FUN_14000ef80
float cosine(uint16_t a) { return trig(a,1); }  // FUN_1400296b0
constexpr float SPEEDS[3] = {1.0f,0.7f,0.5f};   // FUN_14002a6e0 local table
float trunc_round(float v) { return v >= 0.0f ? std::floor(v) : std::ceil(v); }
}

void Pad::update(uint8_t buttons) {              // FUN_1400527f0
    held = buttons; edge = uint16_t(~previous & buttons);
    uint8_t rep = 0, mask = 1;
    for (int i = 0; i < 13; ++i, mask = uint8_t(mask*2)) {
        if (!(buttons & mask)) { started[i] = 0; count[i] = 0; continue; }
        if (count[i] == 0) {
            if (started[i]) { rep |= mask; count[i] = 0; continue; }
            started[i] = 1; count[i] = 10; rep |= mask;
        }
        --count[i];
    }
    repeat = rep; previous = held;
}

Field::Field(const std::vector<std::string>& visible) {
    terrain.reserve(80);
    for (int x = 0; x < W; ++x) raw(x,H-1).type = 0x14;     // floor row (0x5d-1)
    for (int r = 0; r < int(visible.size()); ++r) for (int c = 0; c < 6 && c < int(visible[r].size()); ++c) {
        if (visible[r][c] == '.') continue;
        Body b; b.cx = int8_t(c+1); b.cy = int8_t(r+1); b.x = float(c); b.y = float(r+1-TOP); b.colour = 1;
        terrain.push_back(b);
    }
    for (auto& b : terrain) {
        raw(b.cx,b.cy) = {1,&b};
        auto& col = columns[b.cx];
        auto it = col.begin();
        while (it != col.end() && !((*it)->cy < b.cy)) ++it;   // FUN_14004b420: bottom first
        col.insert(it,&b);
    }
}
void Field::assign(const Field& o) {
    terrain = o.terrain; cells = o.cells;
    const auto map = [&](Body* b) -> Body* {
        if (!b) return nullptr;
        if (b < o.terrain.data() || b >= o.terrain.data() + o.terrain.size())
            throw std::logic_error("Field::assign with attached control puyos");
        return terrain.data() + (b - o.terrain.data());
    };
    for (auto& row : cells) for (auto& c : row) c.body = map(c.body);
    for (int x = 0; x < W; ++x) {
        columns[x].clear();
        for (Body* b : o.columns[x]) columns[x].push_back(map(b));
    }
}
Field::Cell& Field::raw(int x, int y) const {
    return const_cast<Field*>(this)->cells[std::clamp(y,-1,H)+1][std::clamp(x,0,W-1)];
}
Field::Cell& Field::cell(int x, int y) { return raw(x,y); }
static bool skipped(const Body* b) { return b && b->control && !b->solid; }   // slot 0x120 && !0x220

bool Field::blocked(const Body& p, int dx, int dy, float* gap) const {        // FUN_140046bd0
    int x = p.cx + dx, y = p.cy + dy;
    if (x < 1 || W-1 <= x) return true;
    if (y < 0) return false;
    if (H-1 < y) y = H-1;
    const auto& c = raw(x,y);
    if (!c.type || skipped(c.body)) return false;
    if (gap) *gap = float(int(int8_t(y)) - TOP) - p.h;
    return true;
}
bool Field::ground(const Body& p, float y, int dx, int dy) const {            // FUN_140046a10
    int x = p.cx + dx;
    if (!(0 < x && x < W-1)) return true;
    const float ph = p.h; int row = H;
    while (true) {
        const Cell* c;
        do { if (--row < 1) return false; c = &raw(x,row); } while (!c->type || skipped(c->body));
        float h, top;
        if (!c->body) { h = 1.0f; top = float(row - TOP); }
        else { top = c->body->y; h = c->body->h; }
        const float probe = float(dy) + y;
        if (!((h + top) - 0.25f < probe || probe + ph < top + 0.25f)) return true;
    }
}
bool Field::snap(Body& p, float* y) const {                                    // FUN_140045780
    int x = p.cx, cy = p.cy;
    if (!(0 < x && x < W-1 && cy >= 0)) return false;
    if (H-2 < cy) cy = H-2;
    for (int k = -1; k < 2; ++k) {
        const float f1 = *y, f9 = f1 + p.h;
        float f8 = 1.0f, top = float(int(int8_t(k+cy)) - TOP);
        if (k + cy < 0) continue;
        if (k + cy < H) {
            const auto& c = raw(x,k+cy);
            if (!c.type) continue;
            if (c.body) { top = c.body->y; f8 = c.body->h; }
        }
        f8 = f8 + top;
        if (f1 <= f8 - 0.25f && top + 0.25f <= f9) {
            if (top <= f1 && f1 < f8) { *y = f8; return true; }
            if (top < f9 && f9 <= f8) { *y = top - p.h; return true; }
        }
    }
    return false;
}
bool Field::resting(const Body& p) const {                                     // FUN_1400468f0
    int cy = p.cy;
    if (cy < 0) return false;
    if (H-2 < cy) cy = H-2;
    const auto& c = raw(p.cx,cy+1);
    if (!c.type) return false;
    const float f1 = p.y, f2 = p.h;
    float f9;
    if (!c.body) f9 = float(int(int8_t(cy+1)) - TOP);
    else f9 = c.body->y;                      // resting terrain: slot 0xc8 (falling) is false
    return f9 - (f1 + f2) < 0.1f;
}
void Field::settle(Body& p) const {                                            // FUN_1400459b0
    int cy = p.cy;
    if (cy < 0) return;
    if (H-2 < cy) cy = H-2;
    const float f7 = float(p.cx - LEFT) + 0.5f;
    p.x = f7 - p.w*0.5f;
    const auto& c = raw(p.cx,cy+1);
    if (!c.type) return;
    if (!c.body) p.y = float(int(int8_t(cy+1)) - TOP) - p.h;
    else p.y = c.body->y - p.h;               // resting terrain (state != 4)
}
void Field::attach(Body& p) {                                                  // FUN_14004df00(p,1) + 0x6c8
    const int x = p.cx;
    p.cy = int8_t(int8_t(int(p.y)) + TOP);
    if (H-2 < p.cy) p.cy = int8_t(H-2);
    if (p.cy < 0) p.cy = -1;
    auto& col = columns[x];
    float f10 = std::min(p.backup_y,p.y);
    float floor_top = float(int(int8_t(H-1)) - TOP);
    for (Body* b : col) {
        const float top = b->y, h = b->h;
        if (top <= f10) {
            const float bottom = h + top;
            if (p.h - 0.25f <= floor_top - bottom) {
                if (!b->control && p.y < bottom) { p.y = bottom; p.cy = int8_t(b->cy + 1); }
                break;
            }
        }
        if (top < p.h + p.y) p.y = top - p.h;
        if (b->cy <= p.cy) p.cy = int8_t(b->cy - 1);
        if (!b->control) floor_top = top;
    }
    if (p.cy >= 0) raw(x,p.cy) = {1,&p};
    const auto& below = raw(x,p.cy+1);
    if (below.type) {
        const float top = below.body ? below.body->y : float(int(int8_t(p.cy+1)) - TOP);
        if (top - p.h < p.y) p.y = top - p.h;
    }
    p.backup_y = p.y;                                                          // slot 0x1d8
    auto it = col.begin();                                                     // FUN_14004b420
    while (it != col.end() && !((*it)->cy < p.cy)) ++it;
    col.insert(it,&p);
}
void Field::detach(Body& p) {                                                  // FUN_14004ab50
    auto& col = columns[p.cx];
    for (size_t i = 0; i < col.size(); ++i) if (col[i] == &p) {
        if (i > 0) {                                                           // +0xd0: the body below
            const float top = col[i-1]->y;
            if (top < p.h + p.y) p.y = top - p.h;
        }
        col.erase(col.begin()+long(i)); break;
    }
    for (int y = 0; y < H-1; ++y) if (raw(p.cx,y).body == &p) { raw(p.cx,y) = {}; break; }
    p.backup_y = p.y;
}

Controller::Controller(Field& field, Rules rules) : f(field), r(rules) {
    for (auto& b : p) { b.control = true; b.solid = true; b.cy = 0; }
}
void Controller::spawn(Shape s, std::array<int,4> colours) {                   // FUN_140029880
    static constexpr uint32_t codes[] = {0x200,0x300,0x301,0x400,0x401};
    shape = codes[int(s)]; n = int((shape >> 8) & 0xff); active = true; angle = 0; rot = 0;
    ax = 3; ay = 3;                                                           // field slots 0x158 / 0x160
    fx = float(int(ax) - 1); fy = float(int(ay) - 3);
    if (!bit(3)) fy -= 0.5f;
    for (int i = 0; i < n; ++i) {
        auto& b = p[i]; b.colour = colours[i];
        b.x = float(OFFS[0][i][0]) + fx; b.y = float(OFFS[0][i][1]) + fy;   // FUN_14002d2b0 at angle 0
        b.backup_y = b.y;                                                    // FUN_140055470
        b.cx = int8_t(int(b.x + 1.0f)); b.cy = int8_t(int(b.y + 3.0f)); b.solid = true;
    }
    slide = 0; touch = 0; ground_frames = 0; snapped = 0; lift_count = 0; lift = 0;
    anim = 0; anim_idx = 0; anim_y = 0; quick = 0; rot_step = 0; registered = 0;
    touched = false; drop_points = 0;                                         // +0x124
    ddx = fx; ddy = fy;
}
State Controller::state() const {
    return {ax,ay,rot,angle,touch,ground_frames,fx,fy,!active,p[0].colour};
}
std::vector<int> Controller::colours() const {
    std::vector<int> out;
    for (int i = 0; i < n; ++i) out.push_back(p[i].colour);
    return out;
}
std::vector<std::pair<int,int>> Controller::cells() const {
    std::vector<std::pair<int,int>> out;
    for (int i = 0; i < n; ++i) out.push_back({p[i].cx, Field::TOP + int8_t(int(p[i].y))});   // FUN_140049c00
    return out;
}
bool Controller::step(uint8_t buttons) { pad.update(buttons); return update(); }
void Controller::wait(uint8_t buttons) {                                       // FUN_14004d090
    pad.update(buttons);
    if (!r.pad_seat) return;                                                   // Com: slot 0x18 is empty
    const uint16_t rep = pad.repeat, edge = pad.edge;                          // FUN_14002a280
    auto decay = [](int8_t& v) { if (v > 0) --v; if (v < 0) ++v; };
    decay(rotate_buffer); decay(move_buffer);
    // +0x126 (rotation disabled) stays 0 on the Fever path.
    if (edge & 0x20) rotate_buffer = 8;
    if (edge & 0x10) rotate_buffer = -8;
    if (rep & 2) move_buffer = 8;
    if (rep & 1) move_buffer = -8;
}

void Controller::read_input() {                                                // FUN_14002cd80
    const uint16_t held = pad.held, rep = pad.repeat, edge = pad.edge;
    const uint8_t previous = uint8_t(held_prev);
    input = next_input; held_prev = held; next_input = 0;
    if (rep & 1) input |= 1;
    if (rep & 2) input |= 2;
    const uint8_t e = uint8_t(edge);
    if ((held & 1) && (held & 2)) {
        uint16_t mask;
        const bool er = (e >> 1) & 1;
        if (!(edge & 1)) mask = (!er && (previous & 1)) ? 0xfffd : 0xfffe;
        else mask = er ? 0xfffe : 0xfffd;
        input &= mask; held_prev = uint16_t(held & mask);
    }
    if (held & 8) input |= 8;
    uint8_t down = uint8_t(held);
    if (4 < (shape & 0xf)) down = e;
    if (down & 4) input |= 4;
    if ((uint8_t(held) & 0xc) == 0xc && (down & 4)) { input &= 0xfff7; held_prev &= 0xfff7; }
    if (edge & 0x20) input |= 0x20;
    if (edge & 0x10) input |= 0x10;
    if ((e & 0x30) == 0x30) input &= 0xffcf;
    // Buffered presses from the spawn wait (always 0 for the CPU class).
    if ((input & 0x30) == 0) {
        if (rotate_buffer > 0) input |= 0x20;
        else if (rotate_buffer < 0) input |= 0x10;
    }
    rotate_buffer = 0;
    if ((input & 3) == 0) {
        if (move_buffer > 0) input |= 2;
        else if (move_buffer < 0) input |= 1;
    }
    move_buffer = 0;
}
bool Controller::update() {                                                    // FUN_140029e50
    out = 0; sx = fx; sy = fy;
    detach_all();
    for (int i = 0; i < n; ++i) { old[2*i] = p[i].x; old[2*i+1] = p[i].y; }
    read_input();
    const bool landed = frame();
    if (landed) return true;
    if (slide == 0 && anim == 0) fx = float(int(ax) - 1);
    attach_all();
    ddx = fx; ddy = fy;
    return false;
}
bool Controller::frame() {                                                     // FUN_140029b20
    rotate_input(); quick_turn(); rotate_anim(); lift_anim(); move(); fall();
    return land();
}
bool Controller::lockable() {                                                  // FUN_14002c6c0
    if (slide) return false;
    return !(touch < 9 && ground_frames <= uint16_t(r.lock_frames));
}
void Controller::rotate_input() {                                              // FUN_14002b190
    if (lockable()) return;
    const int a = (input >> 5) & 1;
    rot_step = 0x800;
    const int dir = (input & 0x10) ? a - 1 : a;
    if (!dir) return;
    out |= uint8_t(input & 0x30);
    if (anim & 3) { angle = ANGLE[rot]; place(); anim = 0; quick = 0; }
    if (anim == 0) rotate(dir);                                                // kicks call FUN_14002c610 (terrain impulse)
}
void Controller::quick_turn() {                                                // FUN_14002afa0
    if (!(bit(7) && anim == 0 && 1 < quick)) return;
    if (lockable()) return;
    if (input & 0x20) anim = 4;
    if (input & 0x10) anim = 8;
    quick = 0;
    if (!bit(3)) {
        if (rot == 0) {
            float gap = 0;
            if (!free(0,0,1,&gap)) { anim |= 0x40; ++touch; anim_y = gap; anim_idx = 1; ground_frames = 1; }
        }
    } else throw std::logic_error("rule bit3 control path is not ported");
    rot = (rot - 2) & 3;
}
void Controller::rotate_anim() {                                               // FUN_14002d1e0
    if (!(anim & 3)) return;
    quick = 0;
    angle = (anim & 1) ? uint16_t(angle + rot_step) : uint16_t(angle - rot_step);
    place();
    if ((angle & 0x3fff) == 0) anim = 0;
}
void Controller::lift_anim() {                                                 // FUN_14002d0e0
    if (!((shape & 0xf) < 5 && (anim & 0xc))) return;
    const uint16_t a = angle;
    if ((a & 0x7fff) == 0) {
        if (lift < 0.5f) lift = 0;
        else if (++lift_count < 8) lift = 1.0f;
    }
    angle = (anim & 4) ? uint16_t(rot_step*2 + a) : uint16_t(a - rot_step*2);
    place();
    if ((angle & 0x7fff) == 0) anim = 0;
}
void Controller::move() {                                                      // FUN_140029540
    if (slide == 0 && !lockable()) {
        int d = 0;
        if (input & 1) d = -1;
        if (input & 2) d += 1;
        if (d) {
            out |= uint8_t(input & 3);
            if (can_move(d,0)) {
                input &= 0xfff7; ax = uint8_t(ax + d); quick = 0;
                slide = 2; slide_step = float(d)*0.5f;
                snap_after_move(3);
                for (int i = 0; i < n; ++i) p[i].backup_y = p[i].y;       // slot 0x1d8
            }
        }
    }
    if (slide) { input &= 0xfff7; --slide; fx = slide_step + fx; }
}
void Controller::fall() {                                                      // FUN_14002a6e0 (bit3 clear)
    if (anim & 0x40) return;
    bool natural = true;
    speed = r.gravity;
    const float soft = 0.5f;                                                   // slot 0x198
    if ((input & 8) && speed <= soft && soft != speed) { out |= 8; natural = false; speed = soft; }
    if (bit(8) && (input & 4)) throw std::logic_error("rule bit8 hard drop is not ported");
    const float start = trunc_round(fy + lift);
    speed = SPEEDS[r.speed_index]*speed;
    // +0x10c is 1 from the constructor: Down scores a point each time the row grows, until the first touch.
    if (!natural && !touched && start < trunc_round(fy + lift + speed)) ++drop_points;
    float next;
    if (speed < 1.0f) next = fy + speed;
    else {
        int moved = 0;
        const int from = int(start), to = int(speed + fy);
        for (int row = from; row < to; ++row) { if (!can_move(0,row+1-from)) break; ++moved; }
        ++moved;
        next = float(moved) + fy;
    }
    fy = next;
    align();
}
bool Controller::land() {                                                      // FUN_14002ab00 (bit3 clear)
    if (anim & 0x40) return false;
    bool axis = false, any = false;
    float best = -100.0f, d = -100.0f;
    for (int i = 0; i < n; ++i) {
        d = best;
        if (f.resting(p[i])) {
            const float before = p[i].y;
            f.settle(p[i]);
            if (i == 0) axis = true;
            d = before - p[i].y; any = true;
            if (d <= best) d = best;
        }
        best = d;
    }
    if (any) {
        fy -= d;
        snapped = 1; align();
        touched = true;                                                        // +0x124
        if (anim == 0 && slide == 0 && ((input & 8) || lockable())) {
            out |= 8; ++drop_points; finalize(); return true;                  // score slot 0x40 with 1
        }
        if (ground_frames == 0) { ++touch; ground_frames = 1; }
        if (anim == 0 || axis) ++ground_frames;
    } else ground_frames = 0;
    if (!lockable()) return false;
    if (anim == 0 && slide == 0) { finalize(); return true; }
    return false;
}
void Controller::finalize() {                                                  // FUN_14002c800 (bit3 clear)
    align(); ++locks; active = false;
}
void Controller::rotate(int direction) {                                       // FUN_14002c4b0
    anim_idx = 0; anim_y = 0;
    if (n == 2) direction < 0 ? rotate_pair_ccw() : rotate_pair_cw();
    else if (n == 3) direction < 0 ? rotate_triple_ccw() : rotate_triple_cw();
    else if (n == 4) rotate_quad(direction >= 0);
    // slot 0x1a8 -> field 0x5c0: statistics only.
    if (anim & 3) rot = ((anim & 1) ? rot + 1 : rot - 1) & 3;
    for (int i = 0; i < n; ++i) {
        p[i].cx = int8_t(OFFS[rot][i][0] + int8_t(ax));
        p[i].cy = int8_t(OFFS[rot][i][1] + int8_t(ay));
    }
}
bool Controller::free(int i, int dx, int dy, float* gap) { return !f.blocked(p[i],dx,dy,gap); }
bool Controller::ground_free(int i, int dx, int dy) {
    return !f.ground(p[i],float(OFFS[rot][i][1]) + fy,dx,dy);
}
bool Controller::can_move(int dx, int dy) {                                    // FUN_1400292e0 (bit3 clear)
    for (int i = 0; i < n; ++i) p[i].solid = false;
    float lifted = 0.0f;
    if (anim & 0x40) {
        const float y = float(OFFS[rot][anim_idx][1]) + fy;
        if (anim_y < y) lifted = anim_y - y;
    }
    for (int i = 0; i < n; ++i)
        if (f.ground(p[i],float(OFFS[rot][i][1]) + fy + lifted,dx,dy)) return false;   // flags stay cleared
    for (int i = 0; i < n; ++i) p[i].solid = true;
    return true;
}
void Controller::place() {                                                     // FUN_14002a350
    const float c = cosine(angle), s = sine(angle);
    for (int i = 0; i < n; ++i) {
        const float ox = float(OFFS[0][i][0]), oy = float(OFFS[0][i][1]);
        p[i].x = (ox*c - oy*s) + fx;
        p[i].y = oy*c + ox*s + fy;
    }
    if (anim & 0x30) {
        const float px = p[anim_idx].x;
        const float target = float(int(OFFS[rot][anim_idx][0]) + (int(ax) - 1));
        const bool beyond = (anim & 0x20) ? px < target : target < px;
        if (!beyond && px != target) for (int i = 0; i < n; ++i) p[i].x = p[i].x + (target - px);
    }
    if (anim & 0x40) {
        const float want = anim_y, have = p[anim_idx].y;
        if (want < have || have < want) for (int i = 0; i < n; ++i) p[i].y = p[i].y + (want - have);
    }
    fx = p[0].x; fy = p[0].y;
    for (int i = 0; i < n; ++i) p[i].cx = int8_t(int(int8_t(ax)) + OFFS[rot][i][0]);
    sy = fy;   // +0xd8 = +0xd0
    ay = uint8_t(int8_t(int64_t(fy + 3.0f)));
}
void Controller::align() {                                                     // FUN_14002cfd0 (bit3 clear)
    for (int i = 0; i < n; ++i) {
        const int dx = OFFS[rot][i][0], dy = OFFS[rot][i][1];
        p[i].cx = int8_t(dx + int8_t(ax));
        p[i].x = float(dx) + fx; p[i].y = float(dy) + fy;
    }
}
void Controller::snap_after_move(int rows) {                                   // FUN_140029130
    for (int i = 0; i < n; ++i) {
        p[i].cx = int8_t(OFFS[rot][i][0] + int8_t(ax));
        const float base = float(OFFS[rot][i][1]) + fy;
        float y = base;
        if (f.snap(p[i],&y)) for (int j = 0; j < n; ++j) p[j].y = p[j].y + (y - base);
    }
    fx = p[0].x; fy = p[0].y;
    ay = uint8_t(int8_t(int64_t(float(rows) + fy)));
}
void Controller::attach_all() {                                                // FUN_14002c920 (bit3 clear)
    if (registered) detach_all();
    align();
    for (int k = 0; k < 4; ++k) {
        const int i = ORDER[rot][k] - 1;
        if (i >= n) continue;
        if (anim == 0) {
            const float before = p[i].y;
            f.attach(p[i]);
            const float d = p[i].y - before;
            if (d != 0.0f) for (int j = 0; j < n; ++j) if (j != i) p[j].y = p[j].y + d;
        } else if (i == 0) f.attach(p[0]);
        else { const float x = p[i].x, y = p[i].y; f.attach(p[i]); p[i].x = x; p[i].y = y; }
    }
    ay = uint8_t(p[0].cy);
    fx = p[0].x; fy = p[0].y;
    align();
    registered = 1;
}
void Controller::detach_all() {                                                // FUN_14002cbc0
    if (!registered) return;
    for (int k = 0; k < 4; ++k) { const int i = ORDER[rot][k] - 1; if (i < n) f.detach(p[i]); }
    registered = 0;
}

// Rotation kicks, transcribed from slots 0x160..0x188 of vtable 0x1402acb48.
// free(i,dx,dy) is slot 0x110 (true when the cell is open); ground_free is 0x108.
void Controller::rotate_pair_cw() {                                            // FUN_14002b6e0
    float gap = 0;
    switch (rot) {
    case 0:
        if (free(0,1,0,&gap)) { anim = 1; return; }
        if (!(bit(10) && !(gap + 0.25f < fy - 1.0f) && !(bit(9) && ay < 3) && free(0,1,-1,nullptr))) {
            if (free(0,-1,0,nullptr)) { anim = 0x21; anim_idx = 1; ax = uint8_t(ax - 1); return; }
            ++quick; return;
        }
        break;
    case 1:
        if (free(0,0,1,&gap)) {
            anim = 1;
            if (!ground_free(0,0,2)) { ++touch; ground_frames = 1; }
            return;
        }
        if (bit(9) && ay < 3) return;
        if (!free(0,0,-1,nullptr)) return;
        break;
    case 2:
        if (!free(0,-1,0,nullptr)) {
            if (free(0,1,0,nullptr)) { anim = 0x11; anim_idx = 1; ax = uint8_t(ax + 1); return; }
            ++quick; return;
        }
        anim = 1; return;
    case 3:
        if (!free(0,0,-1,nullptr)) {
            if (!free(0,0,1,nullptr)) return;
            ay = uint8_t(ay + 1); anim_y = fy; anim = 0x41; anim_idx = 1; return;
        }
        anim = 1; return;
    default: return;
    }
    ++touch; ay = uint8_t(ay - 1); anim_y = gap; anim = 0x41; anim_idx = 1; ground_frames = 1;
}
void Controller::rotate_pair_ccw() {                                           // FUN_14002b3a0
    float gap = 0;
    switch (rot) {
    case 0:
        if (!free(0,-1,0,&gap)) {
            if (bit(10) && fy - 1.0f <= gap + 0.25f && (!bit(9) || 2 < ay) && free(0,-1,-1,nullptr)) {
                ++touch; ay = uint8_t(ay - 1); anim_y = gap; ground_frames = 1; anim = 0x42; anim_idx = 1; return;
            }
            if (free(0,1,0,nullptr)) { anim = 0x12; anim_idx = 1; ax = uint8_t(ax + 1); return; }
            ++quick; return;
        }
        break;
    case 1:
        if (!free(0,0,-1,nullptr)) {
            if (!free(0,0,1,nullptr)) return;
            ay = uint8_t(ay + 1); anim_y = fy; anim = 0x42; anim_idx = 1; return;
        }
        break;
    case 2:
        if (!free(0,1,0,nullptr)) {
            if (free(0,-1,0,nullptr)) { anim = 0x22; anim_idx = 1; ax = uint8_t(ax - 1); return; }
            ++quick; return;
        }
        break;
    case 3:
        if (free(0,0,1,&gap)) {
            anim = 2;
            if (!ground_free(0,0,2)) { ++touch; ground_frames = 1; }
            return;
        }
        if (bit(9) && ay < 3) return;
        if (!free(0,0,-1,nullptr)) return;
        ++touch; ay = uint8_t(ay - 1); anim_y = gap; anim = 0x42; anim_idx = 1; ground_frames = 1; return;
    default: return;
    }
    anim = 2;
}
void Controller::rotate_triple_cw() {                                          // FUN_14002bdf0
    float gap = 0;
    switch (rot) {
    case 0:
        if (free(0,1,0,&gap)) {
            anim = 1;
            if (ground_free(0,0,2) && ground_free(0,1,1)) return;
            ++touch; ground_frames = 1; return;
        }
        if (!free(0,1,-1,nullptr)) return;
        ++touch; ay = uint8_t(ay - 1); anim_y = gap; anim = 0x41; anim_idx = 2; ground_frames = 1; return;
    case 1:
        if (!free(0,-1,0,nullptr)) {
            if (free(0,1,1,&gap)) {
                anim = 0x11; anim_idx = 2;
                if (!ground_free(0,1,2)) { ++touch; ground_frames = 1; }
                ax = uint8_t(ax + 1); return;
            }
            if (!free(0,0,-1,nullptr)) return;
            if (!free(0,1,-1,nullptr)) return;
            ++touch; ay = uint8_t(ay - 1); ax = uint8_t(ax + 1); anim_y = gap; anim = 0x51; anim_idx = 2;
            ground_frames = 1; return;
        }
        anim = 1;
        if (!ground_free(0,0,2)) { ++touch; ground_frames = 1; }
        return;
    case 2:
        if (free(0,0,-1,&gap)) { anim = 1; return; }
        if (!free(0,-1,1,&gap)) {
            if (!free(0,1,0,nullptr)) return;
            if (!free(0,1,1,nullptr)) return;
            ++touch; ax = uint8_t(ax + 1); ay = uint8_t(ay + 1); anim = 0x51; anim_idx = 1;
            anim_y = fy + 1.0f; ground_frames = 1; return;
        }
        ++touch; ay = uint8_t(ay + 1); anim_y = fy; anim = 0x41; anim_idx = 2; ground_frames = 1; return;
    case 3:
        if (free(0,1,0,&gap)) {
            anim = 1;
            if (ground_free(0,1,1)) return;
            ++touch; ground_frames = 1; return;
        }
        if (!free(0,-1,-1,nullptr)) return;
        anim = 0x21; anim_idx = 2; ax = uint8_t(ax - 1); return;
    default: return;
    }
}
void Controller::rotate_triple_ccw() {                                         // FUN_14002b9f0
    float gap = 0;
    switch (rot) {
    case 0:
        if (free(0,-1,0,&gap)) {
            anim = 2;
            if (!ground_free(0,-1,1)) { ++touch; ground_frames = 1; }
            return;
        }
        if (free(0,1,-1,nullptr)) { ax = uint8_t(ax + 1); anim = 0x12; anim_idx = 1; }
        return;
    case 1:
        if (free(0,0,-1,&gap)) { anim = 2; return; }
        if (free(0,1,1,nullptr)) {
            ++touch; ay = uint8_t(ay + 1); anim = 0x42; anim_idx = 1; anim_y = fy; ground_frames = 1; return;
        }
        if (!free(0,-1,0,nullptr)) return;
        if (!free(0,-1,1,nullptr)) return;
        ++touch; ax = uint8_t(ax - 1); ay = uint8_t(ay + 1); anim = 0x62; anim_idx = 2;
        anim_y = fy + 1.0f; ground_frames = 1; return;
    case 2:
        if (!free(0,1,0,&gap)) {
            if (free(0,-1,1,&gap)) {
                anim = 0x22; anim_idx = 2;
                if (!ground_free(0,-1,2)) { ++touch; ground_frames = 1; }
                ax = uint8_t(ax - 1); return;
            }
            if (!free(0,0,-1,nullptr)) return;
            if (!free(0,-1,-1,nullptr)) return;
            ++touch; ay = uint8_t(ay - 1); ax = uint8_t(ax - 1); anim_y = gap; anim = 0x62; anim_idx = 2;
            ground_frames = 1; return;
        }
        anim = 2;
        if (ground_free(0,0,2)) return;
        ++touch; ground_frames = 1; return;
    case 3:
        if (!free(0,0,1,&gap)) {
            if (!free(0,-1,-1,&gap)) return;
            ++touch; ay = uint8_t(ay - 1); anim_y = gap; anim = 0x42; anim_idx = 1; ground_frames = 1; return;
        }
        anim = 2;
        if (ground_free(0,0,2) && ground_free(0,-1,1)) return;
        ++touch; ground_frames = 1; return;
    default: return;
    }
}
void Controller::rotate_quad(bool cw) {                                        // FUN_14002c330 / FUN_14002c1a0
    if ((shape & 0xf) == 0) {
        // Big puyo: no movement. The colour manager (NEXT slot 0x60) gives the next
        // (slot 0x50, FUN_1400136b0) or previous (slot 0x58, FUN_1400136f0) colour of the
        // identity palette 1..colours (NEXT slot 0x38, 4 in Fever), and every control
        // puyo takes it (body slot 0x2b8).
        static constexpr int colour_count = 4;
        const int c = p[0].colour;
        const int k = (c >= 1 && c <= 5) ? c - 1 : 5;     // palette +0x24 holds 1..5; not found: 5
        const int next = cw ? (k + 1) % colour_count : (k > 0 ? k - 1 : colour_count - 1);
        for (int i = 0; i < n; ++i) p[i].colour = next + 1;
        return;
    }
    for (int k = 0; k < 2; ++k) {
        const int i = ORDER[rot][k] - 1;
        if (i < n && !ground_free(i,0,1)) { ++touch; ground_frames = 1; break; }
    }
    anim = cw ? 1 : 2;
    const auto& o = cw ? QUAD_CW[rot] : QUAD_CCW[rot];
    ax = uint8_t(ax + o[0]);
    fx = float(int(o[0])) + fx; fy = float(int(o[1])) + fy;
}
}

namespace control {
std::vector<Route> explore(const std::vector<std::string>& rows, Shape shape, const Carry& carry, int limit, Rules rules,
                           std::array<int,4> colours, int delay) {
    static constexpr const char* rotations[] = {"", "A", "B", "AA", "BB"};
    std::vector<Route> out;
    std::vector<std::vector<uint8_t>> seen;
    const Field base(rows); Field field;
    // Column heights in game rows: climbing programs only matter next to tall columns.
    std::array<int,7> height{};
    for (int x = 1; x <= 6; ++x) for (int y = 1; y < Field::H-1; ++y)
        if (rows.size() > size_t(y-1) && rows[size_t(y-1)][size_t(x-1)] != '.') { height[size_t(x)] = Field::H-1-y; break; }
    for (const char* rotation : rotations) for (int d = -5; d <= 5; ++d) for (int order = 0; order < 7; ++order) {
        std::vector<uint8_t> rot, mov, prefix;
        for (const char* c = rotation; *c; ++c) rot.push_back(*c == 'A' ? ROTATE_A : ROTATE_B);
        for (int k = 0; k < std::abs(d); ++k) mov.push_back(d < 0 ? LEFT : RIGHT);
        const auto press = [&](uint8_t b) { prefix.push_back(b); prefix.push_back(order == 3 ? DOWN : 0); };
        if (order >= 4) {
            // Climb: a rotation before every column step lifts the piece against a taller
            // column (A, B or alternating), then the final rotations.
            if (!d) continue;
            bool tall = false;
            for (int x = 3; x != 3 + d + (d > 0 ? 1 : -1); x += d > 0 ? 1 : -1)
                if (1 <= x && x <= 6 && height[size_t(x)] >= 10) tall = true;
            if (!tall) continue;
            for (size_t k = 0; k < mov.size(); ++k) {
                press(order == 4 || (order == 6 && k % 2 == 0) ? ROTATE_A : ROTATE_B);
                press(mov[k]);
            }
            for (auto b : rot) press(b);
        } else if (order == 0 || order == 3) {
            for (size_t k = 0; k < std::max(rot.size(),mov.size()); ++k)
                press(uint8_t((k < rot.size() ? rot[k] : 0) | (k < mov.size() ? mov[k] : 0) | (order == 3 ? DOWN : 0)));
        } else {
            const auto& first = order == 1 ? rot : mov; const auto& second = order == 1 ? mov : rot;
            for (auto b : first) press(b);
            for (auto b : second) press(b);
        }
        prefix.insert(prefix.begin(),size_t(std::max(0,delay)),uint8_t(0));
        if (std::find(seen.begin(),seen.end(),prefix) != seen.end()) continue;
        seen.push_back(prefix);
        field.assign(base); Controller c(field,rules); c.restore(carry); c.spawn(shape,colours);
        Route route;
        for (int frame = 0; frame < limit; ++frame) {
            const uint8_t b = frame < int(prefix.size()) ? prefix[size_t(frame)] : uint8_t(DOWN);
            route.program.push_back(b);
            if (c.step(b)) { route.cells = c.cells(); route.colours = c.colours(); route.carry = c.carry(); route.points = c.points(); out.push_back(std::move(route)); break; }
        }
    }
    return out;
}
}
