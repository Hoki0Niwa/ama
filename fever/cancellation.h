#pragma once
#include <cstdlib>
#include <stdexcept>
#ifdef _WIN32
extern "C" {
__declspec(dllimport) void* __stdcall OpenEventA(unsigned long, int, const char*);
__declspec(dllimport) unsigned long __stdcall WaitForSingleObject(void*, unsigned long);
__declspec(dllimport) int __stdcall CloseHandle(void*);
}
#endif
namespace fever { namespace cancellation {
inline bool requested() {
#ifdef _WIN32
    struct Event {
        void* handle;
        Event() : handle(nullptr) {
            const char* name=std::getenv("AMA_FEVER_CANCEL_EVENT");
            if (name) handle=OpenEventA(0x00100000,0,name);
        }
        ~Event() { if (handle) CloseHandle(handle); }
    };
    static Event event;
    return event.handle && WaitForSingleObject(event.handle,0)==0;
#else
    return false;
#endif
}
inline void check() {
    if (requested()) throw std::runtime_error("search cancelled");
}
}}
