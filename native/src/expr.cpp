#include "expr.h"

#include <cctype>
#include <cstdlib>
#include <limits>

namespace refrag {

namespace {
constexpr int kMaxNodes = 512;
constexpr int kMaxParseDepth = 64;
constexpr std::size_t kMaxSourceLength = 4096;
}

void ByteBeatExpr::skip_space() {
    while (cur_ < end_ && (*cur_ == ' ' || *cur_ == '\t' || *cur_ == '\n' || *cur_ == '\r')) {
        ++cur_;
    }
}

int ByteBeatExpr::add_node(Node n) {
    if (nodes_.size() >= static_cast<std::size_t>(kMaxNodes)) {
        failed_ = true;
        return -1;
    }
    nodes_.push_back(n);
    return static_cast<int>(nodes_.size()) - 1;
}

bool ByteBeatExpr::compile(const std::string &text) {
    nodes_.clear();
    root_ = -1;
    valid_ = false;
    source_ = text;
    if (text.size() > kMaxSourceLength) {
        return false;
    }
    std::string trimmed = text;
    if (trimmed.empty()) {
        trimmed = "0";
    }
    cur_ = trimmed.c_str();
    end_ = cur_ + trimmed.size();
    failed_ = false;
    parse_depth_ = 0;
    int node = parse_or();
    skip_space();
    if (failed_ || node < 0 || cur_ != end_) {
        nodes_.clear();
        root_ = -1;
        valid_ = false;
        return false;
    }
    root_ = node;
    valid_ = true;
    return true;
}

int ByteBeatExpr::parse_or() {
    int lhs = parse_xor();
    for (;;) {
        skip_space();
        if (cur_ < end_ && *cur_ == '|' && !(cur_ + 1 < end_ && cur_[1] == '|')) {
            ++cur_;
            int rhs = parse_xor();
            lhs = add_node(Node{Op::Or, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_xor() {
    int lhs = parse_and();
    for (;;) {
        skip_space();
        if (cur_ < end_ && *cur_ == '^') {
            ++cur_;
            int rhs = parse_and();
            lhs = add_node(Node{Op::Xor, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_and() {
    int lhs = parse_shift();
    for (;;) {
        skip_space();
        if (cur_ < end_ && *cur_ == '&' && !(cur_ + 1 < end_ && cur_[1] == '&')) {
            ++cur_;
            int rhs = parse_shift();
            lhs = add_node(Node{Op::And, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_shift() {
    int lhs = parse_additive();
    for (;;) {
        skip_space();
        if (cur_ + 1 < end_ && cur_[0] == '<' && cur_[1] == '<') {
            cur_ += 2;
            int rhs = parse_additive();
            lhs = add_node(Node{Op::Shl, 0, lhs, rhs});
        } else if (cur_ + 1 < end_ && cur_[0] == '>' && cur_[1] == '>') {
            cur_ += 2;
            int rhs = parse_additive();
            lhs = add_node(Node{Op::Shr, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_additive() {
    int lhs = parse_multiplicative();
    for (;;) {
        skip_space();
        if (cur_ < end_ && (*cur_ == '+' || *cur_ == '-')) {
            char op = *cur_;
            ++cur_;
            int rhs = parse_multiplicative();
            lhs = add_node(Node{op == '+' ? Op::Add : Op::Sub, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_multiplicative() {
    int lhs = parse_unary();
    for (;;) {
        skip_space();
        if (cur_ < end_ && (*cur_ == '*' || *cur_ == '/' || *cur_ == '%')) {
            char op = *cur_;
            ++cur_;
            int rhs = parse_unary();
            Op kind = op == '*' ? Op::Mul : (op == '/' ? Op::Div : Op::Mod);
            lhs = add_node(Node{kind, 0, lhs, rhs});
        } else {
            return lhs;
        }
        if (failed_) {
            return -1;
        }
    }
}

int ByteBeatExpr::parse_unary() {
    skip_space();
    if (cur_ < end_ && *cur_ == '-') {
        if (parse_depth_ >= kMaxParseDepth) {
            failed_ = true;
            return -1;
        }
        ++cur_;
        ++parse_depth_;
        int operand = parse_unary();
        --parse_depth_;
        return add_node(Node{Op::Neg, 0, operand, -1});
    }
    if (cur_ < end_ && *cur_ == '~') {
        if (parse_depth_ >= kMaxParseDepth) {
            failed_ = true;
            return -1;
        }
        ++cur_;
        ++parse_depth_;
        int operand = parse_unary();
        --parse_depth_;
        return add_node(Node{Op::Not, 0, operand, -1});
    }
    if (cur_ < end_ && *cur_ == '+') {
        if (parse_depth_ >= kMaxParseDepth) {
            failed_ = true;
            return -1;
        }
        ++cur_;
        ++parse_depth_;
        int operand = parse_unary();
        --parse_depth_;
        return operand;
    }
    return parse_primary();
}

int ByteBeatExpr::parse_primary() {
    skip_space();
    if (cur_ >= end_) {
        failed_ = true;
        return -1;
    }
    if (*cur_ == '(') {
        if (parse_depth_ >= kMaxParseDepth) {
            failed_ = true;
            return -1;
        }
        ++cur_;
        ++parse_depth_;
        int inner = parse_or();
        --parse_depth_;
        skip_space();
        if (cur_ >= end_ || *cur_ != ')') {
            failed_ = true;
            return -1;
        }
        ++cur_;
        return inner;
    }
    if (*cur_ == 't' || *cur_ == 'T') {
        ++cur_;
        if (cur_ < end_ && (std::isalnum(static_cast<unsigned char>(*cur_)) || *cur_ == '_')) {
            failed_ = true;
            return -1;
        }
        return add_node(Node{Op::Var, 0, -1, -1});
    }
    if (std::isdigit(static_cast<unsigned char>(*cur_))) {
        char *stop = nullptr;
        long long value = std::strtoll(cur_, &stop, 10);
        if (stop == cur_) {
            failed_ = true;
            return -1;
        }
        // Reject float literals with an exponent/decimal tail that would parse
        // differently from Python's int() truncation semantics.
        if (stop < end_ && *stop == '.') {
            ++stop;
            while (stop < end_ && std::isdigit(static_cast<unsigned char>(*stop))) {
                ++stop;
            }
        }
        cur_ = stop;
        return add_node(Node{Op::Const, static_cast<std::int64_t>(value), -1, -1});
    }
    failed_ = true;
    return -1;
}

std::int64_t ByteBeatExpr::eval_node(int index, std::int64_t t) const {
    if (index < 0 || index >= static_cast<int>(nodes_.size())) {
        return 0;
    }
    const Node &n = nodes_[index];
    switch (n.op) {
    case Op::Const:
        return n.value;
    case Op::Var:
        return t;
    case Op::Neg:
        return static_cast<std::int64_t>(
            std::uint64_t{0} -
            static_cast<std::uint64_t>(eval_node(n.lhs, t)));
    case Op::Not:
        return ~eval_node(n.lhs, t);
    default:
        break;
    }
    std::int64_t a = eval_node(n.lhs, t);
    std::int64_t b = eval_node(n.rhs, t);
    switch (n.op) {
    case Op::Add:
        return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) +
                                         static_cast<std::uint64_t>(b));
    case Op::Sub:
        return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) -
                                         static_cast<std::uint64_t>(b));
    case Op::Mul:
        return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) *
                                         static_cast<std::uint64_t>(b));
    case Op::Div: {
        if (b == 0) {
            return 0;
        }
        if (a == std::numeric_limits<std::int64_t>::min() && b == -1) {
            return 0;
        }
        // Python floor division.
        std::int64_t q = a / b;
        if ((a % b != 0) && ((a < 0) != (b < 0))) {
            --q;
        }
        return q;
    }
    case Op::Mod: {
        if (b == 0) {
            return 0;
        }
        if (a == std::numeric_limits<std::int64_t>::min() && b == -1) {
            return 0;
        }
        std::int64_t m = a % b;
        if (m != 0 && ((m < 0) != (b < 0))) {
            m += b;
        }
        return m;
    }
    case Op::Shl: {
        if (b < 0 || b > 62) {
            return 0;
        }
        return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) << b);
    }
    case Op::Shr: {
        if (b < 0) {
            return 0;
        }
        if (b > 62) {
            return a < 0 ? -1 : 0;
        }
        return a >> b;
    }
    case Op::And:
        return a & b;
    case Op::Or:
        return a | b;
    case Op::Xor:
        return a ^ b;
    default:
        return 0;
    }
}

std::int64_t ByteBeatExpr::eval(std::int64_t t) const {
    if (!valid_) {
        return 0;
    }
    return eval_node(root_, t);
}

}  // namespace refrag
