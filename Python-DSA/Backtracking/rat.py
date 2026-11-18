class Solution:
    DIRS = [(1, 0, 'D'), (0, -1, 'L'), (0, 1, 'R'), (-1, 0, 'U')]

    def ratInMaze(self, maze: list[list[int]]) -> list[str]:
        # code here
        n = len(maze)
        path = []
        ans = []

        self.backtrack(n, maze, ans, path, 0, 0)
        return ans

    def is_solution(self, row, col, n):
        if row == (n - 1) and col == (n - 1):
            return True
        return False

    def is_valid(self, row, col, maze, n):
        if 0 <= row <= (n - 1) and 0 <= col <= (n - 1) and maze[row][col] == 1:
            return True
        return False

    def make_choice(self, row, col, maze, move, path):
        maze[row][col] = 0
        path.append(move)

    def undo_choice(self, row, col, maze, path):
        maze[row][col] = 1
        path.pop()

    def backtrack(self, n, maze, ans, path, row, col):
        if self.is_solution(row, col, n):
            ans.append("".join(path))
            return
        for choices in self.DIRS:
            move = choices[2]
            new_row = row + choices[0]
            new_col = col + choices[1]
            if self.is_valid(row, col, maze, n):
                self.make_choice(row, col, maze, move, path)
                self.backtrack(n, maze, ans, path, new_row, new_col)
                self.undo_choice(row, col, maze, path)

        return


s = Solution()
print(s.ratInMaze([[1, 0, 0, 0], [1, 1, 0, 1], [1, 1, 0, 0], [0, 1, 1, 1]]))
