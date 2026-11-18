class QueemsProblem:
    def __init__(self, n):
        self.n = n
        self.chess_board = [[0 for i in range(n)] for j in range(n)]

    def print_board(self):
        for i in range(self.n):
            for j in range(self.n):
                print(self.chess_board[i][j], end=" ")
            print()

    def is_safe(self, row, col):
        # Check this row on left side
        for i in range(col):
            if self.chess_board[row][i] == 1:
                return False

        # Check upper diagonal on left side
        for i, j in zip(range(row, -1, -1), range(col, -1, -1)):
            if self.chess_board[i][j] == 1:
                return False

        # Check lower diagonal on left side
        for i, j in zip(range(row, self.n), range(col, -1, -1)):
            if self.chess_board[i][j] == 1:
                return False

        return True

    def solve_n_queens_util(self, col):
        # base case: If all queens are placed, return True
        if col >= self.n:
            return True

        # Consider this column and try placing this queen in all rows one by one
        for i in range(self.n):
            if self.is_safe(i, col):
                # Place queen
                self.chess_board[i][col] = 1

                # Recur to place the rest of the queens
                if self.solve_n_queens_util(col + 1):
                    return True

                # If placing queen in this position doesn't lead to a solution,
                # then backtrack and remove the queen from this position
                self.chess_board[i][col] = 0

        # If the queen cannot be placed in any row in this column, return False
        return False

    def solve_n_queens(self):
        if not self.solve_n_queens_util(0):
            print("Solution does not exist")
            return False

        self.print_board()
        return True


q = QueemsProblem(4)
q.solve_n_queens()
