def dfs_on_matrix(matrix, row, col, visited):
    # Check if the current position is out of bounds or already visited
    if (row < 0 or row >= len(matrix) or
            col < 0 or col >= len(matrix[0]) or
            visited[row][col]):
        return

    # Mark the current position as visited
    visited[row][col] = True

    # Process the current cell (for example, print its value)
    print(matrix[row][col])

    # Explore the neighboring cells (up, down, left, right)
    dfs_on_matrix(matrix, row - 1, col, visited)  # Up
    dfs_on_matrix(matrix, row + 1, col, visited)  # Down
    dfs_on_matrix(matrix, row, col - 1, visited)  # Left
    dfs_on_matrix(matrix, row, col + 1, visited)  # Right


matrix = [
    [1, 2, 3],
    [4, 5, 6],
    [7, 8, 9]
]
visited = [[False] * len(matrix[0]) for _ in range(len(matrix))]
dfs_on_matrix(matrix, 0, 0, visited)
