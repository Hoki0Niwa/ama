#pragma once

#include "def.h"
#include "cell.h"
#include "direction.h"

class FieldBit
{
public:
    __m128i data;
public:
    FieldBit();
public:
    bool operator == (const FieldBit& other);
    bool operator != (const FieldBit& other);
    FieldBit operator | (const FieldBit& other);
    FieldBit operator & (const FieldBit& other);
    FieldBit operator ^ (const FieldBit& other);
    FieldBit operator ~ ();
public:
    void set_bit(i8 x, i8 y);
    bool get_bit(i8 x, i8 y);
    u32 get_count();
    u16 get_col(i8 x);
    FieldBit get_expand();
    FieldBit get_mask_12();
    FieldBit get_mask_13();
    FieldBit get_mask_pop();
    FieldBit get_mask_group(i8 x, i8 y);
    FieldBit get_mask_group_4(i8 x, i8 y);
    FieldBit get_mask_group_lsb();
public:
    bool is_empty();
public:
    void pop(FieldBit& mask);
    void print();
};
// Keep small operations visible to callers in the search hot path.
inline FieldBit::FieldBit()
{
    this->data = _mm_setzero_si128();
};

inline bool FieldBit::operator == (const FieldBit& other)
{
    __m128i neq = _mm_xor_si128(this->data, other.data);
    return _mm_test_all_zeros(neq, neq);
};

inline bool FieldBit::operator != (const FieldBit& other)
{
    __m128i neq = _mm_xor_si128(this->data, other.data);
    return !_mm_test_all_zeros(neq, neq);
};

inline FieldBit FieldBit::operator | (const FieldBit& other)
{
    FieldBit result;
    result.data = this->data | other.data;
    return result;
};

inline FieldBit FieldBit::operator & (const FieldBit& other)
{
    FieldBit result;
    result.data = this->data & other.data;
    return result;
};

inline FieldBit FieldBit::operator ^ (const FieldBit& other)
{
    FieldBit result;
    result.data = this->data ^ other.data;
    return result;
};

inline FieldBit FieldBit::operator ~ ()
{
    FieldBit result;
    result.data = ~this->data;
    return result;
};

// Turns on a bit
inline void FieldBit::set_bit(i8 x, i8 y)
{
    assert(x >= 0 && x < 6);

    alignas(16) u16 v[8];
    _mm_store_si128((__m128i*)v, this->data);

    v[x] |= 1 << y;

    this->data = _mm_load_si128((const __m128i*)v);
};

// Checks if a bit is set
inline bool FieldBit::get_bit(i8 x, i8 y)
{
    if (x < 0 || x > 5 || y < 0 || y > 12) {
        return false;
    }

    alignas(16) u16 v[8];
    _mm_store_si128((__m128i*)v, this->data);

    return v[x] & (1 << y);
};

// Returns the number of set bits
inline u32 FieldBit::get_count()
{
    alignas(16) u64 v[2];
    _mm_store_si128((__m128i*)v, this->data);

    return std::popcount(v[0]) + std::popcount(v[1]);
};

// Returns a column of the bitfield
inline u16 FieldBit::get_col(i8 x)
{
    assert(x >= 0 && x < 6);

    alignas(16) u16 v[8];
    _mm_store_si128((__m128i*)v, this->data);

    return v[x];
};

// Expands a bitfield and returns the result
// Ex:
    // ......      ......
    // ......      .XX...
    // .XX...  ->  XXXX..
    // ......      .XX..X
    // .....X      ....XX
inline FieldBit FieldBit::get_expand()
{
    __m128i r = _mm_srli_si128(this->data, 2);
    __m128i l = _mm_slli_si128(this->data, 2);
    __m128i u = _mm_srli_epi16(this->data, 1);
    __m128i d = _mm_slli_epi16(this->data, 1);

    auto result = *this;
    result.data |= r | l | u | d;

    return result;
};

// Returns the bitfield with only the 12 lower bits
inline FieldBit FieldBit::get_mask_12()
{
    FieldBit result = *this;
    result.data &= _mm_set_epi16(0, 0, 0x0FFF, 0x0FFF, 0x0FFF, 0x0FFF, 0x0FFF, 0x0FFF);

    return result;
};

// Returns the bitfield with only the 13 lower bits
inline FieldBit FieldBit::get_mask_13()
{
    FieldBit result = *this;
    result.data &= _mm_set_epi16(0, 0, 0x1FFF, 0x1FFF, 0x1FFF, 0x1FFF, 0x1FFF, 0x1FFF);

    return result;
};

// Returns if the bitfield is empty
inline bool FieldBit::is_empty()
{
    return _mm_testz_si128(this->data, this->data);
};
