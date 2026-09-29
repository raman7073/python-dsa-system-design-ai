"""
 Question Link: https://www.geeksforgeeks.org/batch/cip-1/track/P100-Searching/problem/peak-element

   Given an array arr[] where no two adjacent elements are same, find the index of a peak element. 
   An element is considered to be a peak if it is greater than its adjacent elements (if they exist).

   If there are multiple peak elements, Return index of any one of them.
   The output will be "true" if the index returned by your function is correct; otherwise, it will be "false".

   Note: Consider the element before the first element and the element after the last element to be negative infinity.

Examples :

Input: arr = [1, 2, 4, 5, 7, 8, 3]
Output: true
Explanation: arr[5] = 8 is a peak element because arr[4] < arr[5] > arr[6].
Input: arr = [10, 20, 15, 2, 23, 90, 80]
Output: true
Explanation: Element 20 at index 1 is a peak since 10 < 20 > 15. Index 5 (value 90) is also a peak, but returning any one peak index is valid.


Solution :
The straightforward interview solution is to scan every element and check its neighbours, taking O(n) time and O(1) extra space.
To improve it, we’ll explore a binary-search idea: use the direction of the slope to choose where to search.
Start with:
left = 0right = 6mid = (left + right) // 2  # 3


Compare the middle element with its right neighbour:
arr[mid]    
# 2
 
arr[mid + 1] 
# 23


The values rise from 2 to 23.

Since 23 > 2, 23 already beats its left neighbour. Now imagine following the values to the right. There are only two possible outcomes:
1. The values eventually decrease.
   The element immediately before the first decrease is a peak: we climbed up to it, then went down.
   In our example, 2 < 23 < 90 > 80, so 90 is a peak.
2. The values keep increasing until the array ends.
   The last element is a peak: it beats its left neighbour, and its imaginary right neighbour is negative infinity.
   For example, in [2, 23, 90, 100], 100 is a peak.
So an upward slope guarantees at least one peak somewhere to the right. Because any peak is acceptable, we can narrow our search:
left = mid + 1  # left becomes 4


The imaginary walk explains the guarantee; our algorithm continues using midpoint jumps.
Now the next step is:
left = 4
right = 6
mid = 5
# arr[mid]     is 90
# arr[mid + 1] is 80


We now have a downward slope
right = mid keeps mid as a candidate, because it could itself be the peak.
If arr[mid] also beats its left neighbour, it is a peak. 
Otherwise, the values rise toward the left, guaranteeing a peak in that direction.

"""


def peak_index(arr):
    left = 0
    right = len(arr) - 1

    while left < right:
        mid = (left + right) // 2

        if arr[mid] < arr[mid + 1]:
            left = mid + 1  # A peak exists to the right
        else:
            right = mid    # A peak exists at mid or to its left

    return left
