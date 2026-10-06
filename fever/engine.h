#pragma once

#include "search.h"

// The solo chain builder as a function, so that the fever engine and the battle worker answer a
// build request with the same code. The request and the reply are described in fever/main.cpp.
namespace fever
{

json answer(const json& input, const beam::eval::Weight& w, const json& set);

// Reads the weight set of a config file: false when the file can't be opened
bool load_weights(const std::string& path, beam::eval::Weight& w, json& set);

};
