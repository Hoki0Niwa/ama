#pragma once

#include <iostream>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <time.h>
#include <cmath>
#include <chrono>
#include <vector>
#include <array>
#include <unordered_map>
#include <cassert>
#include <algorithm>
#include <bitset>
#include <bit>
#include <thread>
#include <limits>
#include <mutex>
#include <atomic>
#include <optional>
#include <x86intrin.h>
#include <condition_variable>
#include <numeric>
#include <stdalign.h>
#include <functional>
#include <iterator>

using i8 = int8_t;
using i16 = int16_t;
using i32 = int32_t;
using i64 = int64_t;
using i128 = __int128;

using u8 = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using u64 = uint64_t;
using u128 = unsigned __int128;

using f32 = float;
using f64 = double;

using usize = size_t;

#if defined(__GNUC__) && !defined(PEXT)
// Keep the executable portable. Only this function requires BMI2, selected once
// by CPUID; unsupported processors retain the software path below.
__attribute__((target("bmi2"))) inline u16 pext16_bmi2(u16 input, u16 mask)
{
    return u16(_pext_u32(input, mask));
};
#endif

inline u16 pext16(u16 input, u16 mask)
{
#ifdef PEXT
    return _pext_u32(u32(input), u32(mask));
#else
#if defined(__GNUC__) && !defined(AMA_SOFTWARE_PEXT)
    static const bool bmi2 = __builtin_cpu_supports("bmi2");
    if (bmi2) {
        return pext16_bmi2(input, mask);
    }
#endif
    u16 result = 0;

    for (u16 bb = 1; mask != 0; bb += bb) {
        if (input & mask & -mask) {
            result |= bb;
        }
        
        mask &= (mask - 1);
    }

    return result;
#endif
};
