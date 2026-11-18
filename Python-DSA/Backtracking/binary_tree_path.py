# Definition for a binary tree node.
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


class Solution:
    def binaryTreePaths(self, root: TreeNode | None) -> list[str]:
        if root is None:
            return []
        path = [str(root.val)]  # path always holds root -> current node
        ans = []
        self.backtrack(root, path, ans)
        return ans

    def backtrack(self, node, path, ans):
        # base case: reached a leaf -> record the solution
        if node.left is None and node.right is None:
            ans.append("->".join(path))
            return

        # choices: the children of the current node
        for child in [node.left, node.right]:
            if child is not None:              # is the choice valid?
                path.append(str(child.val))    # make the choice
                self.backtrack(child, path, ans)  # explore
                path.pop()                     # undo the choice


# Usage
s = Solution()
# s.binaryTreePaths(TreeNode(1, TreeNode(2, None, TreeNode(5)), TreeNode(3)))
# Output: ['1->2->5', '1->3']
print(s.binaryTreePaths(TreeNode(1, TreeNode(2, None, TreeNode(5)), TreeNode(3))))
