"""Minimal VT100/ncurses screen emulator for the real CMatrix PTY output.

CMatrix writes through ncurses, which emits cursor-addressing escape sequences
rather than a plain stream of characters. This parser reconstructs the terminal
grid from those sequences so the browser can draw the *actual* process output.
It is deliberately small: only the control sequences ncurses emits for cmatrix
are implemented, and unknown sequences are ignored rather than guessed.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass


@dataclass(slots=True)
class TerminalFrame:
    cols: int
    rows: int
    lines: list[str]
    intensity: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "lines": self.lines,
            "intensity": self.intensity,
        }


class TerminalScreen:
    def __init__(self, *, rows: int = 24, cols: int = 80) -> None:
        self.rows = max(4, rows)
        self.cols = max(20, cols)
        self.chars = [[" "] * self.cols for _ in range(self.rows)]
        self.attrs = [[0] * self.cols for _ in range(self.rows)]
        self.row = 0
        self.col = 0
        self.saved = (0, 0)
        self.attr = 1
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.state = "ground"
        self.buffer = ""
        self.dirty = True

    def reset(self) -> None:
        self.chars = [[" "] * self.cols for _ in range(self.rows)]
        self.attrs = [[0] * self.cols for _ in range(self.rows)]
        self.row = self.col = 0
        self.attr = 1
        self.dirty = True

    def feed(self, data: bytes) -> None:
        for char in self._decoder.decode(data):
            self._feed_char(char)

    def _feed_char(self, char: str) -> None:
        if self.state == "esc":
            if char == "[":
                self.state = "csi"
                self.buffer = ""
            elif char == "]":
                self.state = "osc"
                self.buffer = ""
            elif char == "7":
                self.saved = (self.row, self.col)
                self.state = "ground"
            elif char == "8":
                self.row, self.col = self.saved
                self.state = "ground"
            elif char in "()":
                self.state = "charset"
            else:
                self.state = "ground"
            return
        if self.state == "charset":
            self.state = "ground"
            return
        if self.state == "osc":
            if char == "\x07" or char == "\x1b":
                self.state = "ground"
            return
        if self.state == "csi":
            self.buffer += char
            if char.isalpha() or char in "~@":
                self._csi(self.buffer[:-1], char)
                self.state = "ground"
            return
        if char == "\x1b":
            self.state = "esc"
            return
        if char == "\r":
            self.col = 0
        elif char == "\n":
            self.row = min(self.rows - 1, self.row + 1)
        elif char == "\b":
            self.col = max(0, self.col - 1)
        elif char == "\t":
            self.col = min(self.cols - 1, (self.col // 8 + 1) * 8)
        elif char >= " " and char != "\x7f":
            self._put(char)

    def _put(self, char: str) -> None:
        if self.row >= self.rows or self.col >= self.cols:
            return
        self.chars[self.row][self.col] = char
        self.attrs[self.row][self.col] = self.attr
        self.col += 1
        if self.col >= self.cols:
            self.col = 0
            self.row = min(self.rows - 1, self.row + 1)
        self.dirty = True

    def _csi(self, params: str, final: str) -> None:
        private = params.startswith("?")
        clean = params.lstrip("?><")
        nums = [int(p) if p.isdigit() else 0 for p in clean.split(";") if p != ""]
        a = nums[0] if nums else 0
        b = nums[1] if len(nums) > 1 else 0
        if final in ("H", "f"):
            self.row = max(0, min(self.rows - 1, a - 1))
            self.col = max(0, min(self.cols - 1, (b or 1) - 1))
        elif final == "A":
            self.row = max(0, self.row - max(1, a))
        elif final == "B":
            self.row = min(self.rows - 1, self.row + max(1, a))
        elif final == "C":
            self.col = min(self.cols - 1, self.col + max(1, a))
        elif final == "D":
            self.col = max(0, self.col - max(1, a))
        elif final == "G":
            self.col = max(0, min(self.cols - 1, a - 1))
        elif final == "d":
            self.row = max(0, min(self.rows - 1, a - 1))
        elif final == "J":
            mode = a or 0
            if mode == 2:
                self.reset()
            elif mode == 0:
                for c in range(self.col, self.cols):
                    self.chars[self.row][c] = " "
                    self.attrs[self.row][c] = 0
                for r in range(self.row + 1, self.rows):
                    for c in range(self.cols):
                        self.chars[r][c] = " "
                        self.attrs[r][c] = 0
                self.dirty = True
        elif final == "K":
            start = 0 if a == 1 else self.col if a == 0 else 0
            end = self.cols if a != 1 else self.col + 1
            for c in range(start, min(self.cols, end)):
                self.chars[self.row][c] = " "
                self.attrs[self.row][c] = 0
            self.dirty = True
        elif final == "m":
            if not nums:
                nums = [0]
            for code in nums:
                if code == 0:
                    self.attr = 1
                elif code in (1, 37, 97):
                    self.attr = 2
                elif code in (2, 22, 32, 92, 39):
                    self.attr = 1
        elif final == "s":
            self.saved = (self.row, self.col)
        elif final == "u":
            self.row, self.col = self.saved
        elif final in ("h", "l") and private:
            pass  # ?25l/h cursor visibility, ?1049h alternate screen
        # r (scroll region), L/M (insert/delete lines), P/X, n, t are ignored.

    def snapshot(self) -> TerminalFrame:
        lines = ["".join(row).rstrip() for row in self.chars]
        intensity = [
            "".join(str(min(2, v)) for v in attrs)[: len(lines[i])]
            for i, attrs in enumerate(self.attrs)
        ]
        return TerminalFrame(cols=self.cols, rows=self.rows, lines=lines, intensity=intensity)
