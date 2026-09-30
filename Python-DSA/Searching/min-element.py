"""
Question Link : https://www.geeksforgeeks.org/batch/cip-1/track/P100-Searching/problem/minimum-number-in-a-sorted-rotated-array-1587115620

Given an array of distinct elements which was initially sorted. This array may be rotated at some unknown point. The task is to find the minimum element in the given sorted and rotated array. 

Example 1:

Input:
N = 10
arr[] = {2,3,4,5,6,7,8,9,10,1}
Output: 1
Explanation: The array is rotated 
once anti-clockwise. So minimum 
element is at last index (n-1) 
which is 1.


Soution: 
1. Define the initial search space.
   “Initially, the minimum could be anywhere,
   so my search space is the inclusive range [left, right], from 0 to n - 1.”
2. State what must always remain true.
   “The minimum must always remain inside [left, right].”
   This is our invariant—a fact that remains true after every update.
3. Explain why each elimination is safe.
Comparison	                         Reasoning	                                      New search space
arr[mid] > arr[right]	           The rotation’s drop lies after mid. 
                                   The minimum must be strictly to its right.	          [mid + 1, right]

arr[mid] < arr[right]              The section from mid through right is increasing. 
                                   Nothing after mid can beat arr[mid], 
                                   but mid itself could be the minimum.	                   [left, mid]


That gives us:
if arr[mid] > arr[right]:    left = mid + 1else:    right = mid


Every update must do two things: preserve the minimum and shrink the search space.
For example:
arr = [30, 10, 20]


Search space: indexes	Comparison	Remaining indexes
[0, 2]	arr[1] = 10 < 20	[0, 1]: keep mid
[0, 1]	arr[0] = 30 > 10	[1, 1]: discard mid


Now explain termination:
“When left == right, only one candidate remains. 
Since every update preserved the minimum, that candidate must be the minimum.
I return arr[left].”
Finally, explain complexity:
“Each iteration roughly halves the search space, so the time complexity is O(log n).
I maintain only a few variables, so extra space is O(1).”

"""


def find_minimum(arr):
    left = 0
    right = len(arr) - 1

    while left < right:
        mid = (left + right) // 2

        if arr[mid] > arr[right]:
            left = mid + 1
        else:
            right = mid

    return arr[left]
