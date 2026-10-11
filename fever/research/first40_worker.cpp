// Reuse the exact production request dispatcher and physics, replacing only
// the translation units selected by the research build script.
#define main ama_original_worker_main
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
#include "../../fever_battle/main.cpp"
#pragma GCC diagnostic pop
#undef main
#include "first40_diagnostics.h"

int main() {
    std::string line;
    while(std::getline(std::cin,line)) {
        if(line.empty())continue;
        try {
            auto request=json::parse(line);
            const bool on=request.value("research_diagnostics",false);
            if(on && (request.value("op","")!="solo" || request.at("request").at("self").at("queue").size()>3))
                throw std::invalid_argument("diagnostics requires solo and at most three visible pieces");
            if(on && (request.contains("seed") || request.at("request").contains("seed")))
                throw std::invalid_argument("environment seed is forbidden in diagnostic solo requests");
            const int t=request.value("research_placed_total",0);
            if(on && (t<0 || t>=40))throw std::invalid_argument("placed_total outside opening");
            fever::research::begin_request(on,t,request.value("research_detail_all",false));
            auto reply=answer(request);
            if(on)reply["research_diagnostics"]=fever::research::finish_request();
            else fever::research::enabled=false;
            std::cout<<reply.dump()<<std::endl;
        }catch(const std::exception& e) {
            fever::research::enabled=false;
            std::cout<<json{{"error",e.what()}}.dump()<<std::endl;
        }
    }
}
