def matrix_recursive_traversal(matrix, row=0, col=0):
    """
    Recursively traverses a 2D matrix and prints its elements in a row-wise manner.

    Args:
        matrix (list of list): The 2D matrix to traverse.
        row (int): The current row index.
        col (int): The current column index.
    """
    # Base case: If we have traversed all rows
    if row >= len(matrix):
        return

    # Print the current element
    print(matrix[row][col], end=' ')

    # Move to the next column
    if col + 1 < len(matrix[row]):
        matrix_recursive_traversal(matrix, row, col + 1)
    else:
        # Move to the next row and reset column index
        print()  # New line for the next row
        matrix_recursive_traversal(matrix, row + 1, 0)


# Example usage
if __name__ == "__main__":
    matrix = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9]
    ]
    matrix_recursive_traversal(matrix)
