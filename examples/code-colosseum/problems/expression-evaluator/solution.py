class _Parser:
    def __init__(self, expr: str):
        self.expr = expr
        self.pos = 0
        self.length = len(expr)

    def _peek(self) -> str:
        self._skip_whitespace()
        if self.pos >= self.length:
            return ""
        return self.expr[self.pos]

    def _consume(self) -> str:
        ch = self.expr[self.pos]
        self.pos += 1
        return ch

    def _skip_whitespace(self) -> None:
        while self.pos < self.length and self.expr[self.pos].isspace():
            self.pos += 1

    def _expect(self, expected: str) -> None:
        self._skip_whitespace()
        if self.pos >= self.length or self.expr[self.pos] != expected:
            raise ValueError("unexpected token")
        self.pos += 1

    def parse(self) -> float:
        if not self.expr or self.expr.strip() == "":
            raise ValueError("empty expression")
        value = self._parse_expr()
        self._skip_whitespace()
        if self.pos != self.length:
            raise ValueError("trailing characters")
        return float(value)

    def _parse_expr(self) -> float:
        value = self._parse_term()
        while True:
            ch = self._peek()
            if ch == "+":
                self._consume()
                value += self._parse_term()
            elif ch == "-":
                self._consume()
                value -= self._parse_term()
            else:
                break
        return value

    def _parse_term(self) -> float:
        value = self._parse_factor()
        while True:
            ch = self._peek()
            if ch == "*":
                self._consume()
                value *= self._parse_factor()
            elif ch == "/":
                self._consume()
                divisor = self._parse_factor()
                if divisor == 0:
                    raise ValueError("division by zero")
                value /= divisor
            else:
                break
        return value

    def _parse_factor(self) -> float:
        ch = self._peek()
        if ch == "+":
            self._consume()
            return self._parse_factor()
        if ch == "-":
            self._consume()
            return -self._parse_factor()
        return self._parse_primary()

    def _parse_primary(self) -> float:
        ch = self._peek()
        if ch == "":
            raise ValueError("unexpected end of expression")
        if ch == "(":
            self._consume()
            value = self._parse_expr()
            self._expect(")")
            return value
        return self._parse_number()

    def _parse_number(self) -> float:
        self._skip_whitespace()
        start = self.pos
        saw_dot = False
        while self.pos < self.length:
            ch = self.expr[self.pos]
            if ch.isdigit():
                self.pos += 1
            elif ch == "." and not saw_dot:
                saw_dot = True
                self.pos += 1
            else:
                break
        if start == self.pos:
            raise ValueError("number expected")
        return float(self.expr[start : self.pos])


def evaluate(expr: str) -> float:
    return _Parser(expr).parse()
