// Minimal, allocation-free bytebeat expression evaluator for the 8BitSynth.
// This is the only expression implementation: integer literals, the variable
// `t`, unary -/~ and + - * / % << >> & | ^ with C precedence, evaluated with
// Python's floor-division/modulo semantics and wrap-around integer overflow.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace refrag {

class ByteBeatExpr {
  public:
    // Returns true when `text` compiled cleanly.  An empty source compiles to
    // 0; a failed compile stays invalid so the machine renders silence.
    bool compile(const std::string &text);

    bool valid() const { return valid_; }

    const std::string &source() const { return source_; }

    std::int64_t eval(std::int64_t t) const;

  private:
    enum class Op : std::uint8_t {
        Const,
        Var,
        Neg,
        Not,
        Add,
        Sub,
        Mul,
        Div,
        Mod,
        Shl,
        Shr,
        And,
        Or,
        Xor,
    };

    struct Node {
        Op op = Op::Const;
        std::int64_t value = 0;
        int lhs = -1;
        int rhs = -1;
    };

    std::vector<Node> nodes_;
    int root_ = -1;
    bool valid_ = false;
    std::string source_;

    // Recursive-descent parser state.
    const char *cur_ = nullptr;
    const char *end_ = nullptr;
    bool failed_ = false;
    int parse_depth_ = 0;

    void skip_space();
    int add_node(Node n);
    int parse_or();
    int parse_xor();
    int parse_and();
    int parse_shift();
    int parse_additive();
    int parse_multiplicative();
    int parse_unary();
    int parse_primary();
    std::int64_t eval_node(int index, std::int64_t t) const;
};

}  // namespace refrag
