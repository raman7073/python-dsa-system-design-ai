class QueensProblem:
    def __init__(self, n):
        self.n = n
        self.board = [[0] * n for _ in range(n)]

    # ---------- generic template (don't change) ----------
    def backtrack(self, state):
        if self.is_complete(state):              # 1. base case
            return True
        for choice in self.get_choices():   # 2. choices
            if self.is_valid(state, choice):     # 3. prune
                self.make_choice(state, choice)  # 4. choose
                if self.backtrack(self.next_state(state)):  # 5. explore
                    return True
                self.undo_choice(state, choice)  # 6. un-choose
        return False                             # 7. dead end

    # ---------- problem-specific pieces ----------
    def is_complete(self, col):
        return col >= self.n

    def get_choices(self):
        return range(self.n)                     # every row

    def is_valid(self, col, row):
        for c in range(col):                     # same row, left side
            if self.board[row][c]:
                return False
        for r, c in zip(range(row, -1, -1), range(col, -1, -1)):   # upper-left
            if self.board[r][c]:
                return False
        for r, c in zip(range(row, self.n), range(col, -1, -1)):   # lower-left
            if self.board[r][c]:
                return False
        return True

    def make_choice(self, col, row):
        self.board[row][col] = 1

    def undo_choice(self, col, row):
        self.board[row][col] = 0

    def next_state(self, col):
        return col + 1

    # ---------- driver ----------
    def print_board(self):
        for r in self.board:
            print(*r)

    def solve(self):
        if not self.backtrack(0):                # start state = column 0
            print("Solution does not exist")
            return False
        self.print_board()
        return True


QueensProblem(4).solve()
