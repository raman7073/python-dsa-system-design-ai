"""
Question  Link: https://www.geeksforgeeks.org/batch/cip-1/track/P100-Searching/problem/floor-in-a-sorted-array-1587115620
Given a sorted array arr[] and an integer x, 
find the index (0-based) of the largest element in arr[] that is less than or equal to x. 
This element is called the floor of x. If such an element does not exist, return -1.

Note: In case of multiple occurrences of floor of x, return the index of the last occurrence.

Examples

Input: arr[] = [1, 2, 8, 10, 10, 12, 19], x = 5
Output: 1
Explanation: Largest number less than or equal to 5 is 2, whose index is 1.
Input: arr[] = [1, 2, 8, 10, 10, 12, 19], x = 11
Output: 4
Explanation: Largest Number less than or equal to 11 is 10, whose indices are 3 and 4. The index of last occurrence is 4.
Input: arr[] = [1, 2, 8, 10, 10, 12, 19], x = 0
Output: -1
Explanation: No element less than or equal to 0 is found. So, output is -1.

Solution:

We can use the same idea as our first-occurrence problem: 
save a valid candidate, then continue searching for a better index.
Start here:
left = 0
right = len(arr) - 1 
# 6
# answer = -1    
# No valid candidate found yet
mid = (left + right) // 2  
# 3


At index 3, the value is 10. Since 10 <= 11, this is a valid candidate.
Save index 3, then search to its right:
answer = mid    
# 3
left = mid + 1 
# 4


A later valid index could contain either a larger value still ≤ x,
or another occurrence of the same value. Both would improve our answer.
Now:
left = 4
right = 6
answer = 3
mid = (left + right) // 2  
# 5


At index 5, we find 12, but our target is 11.
12 > 11, so index 5 cannot qualify. 
Because the array is sorted, everything to its right is also too large.
right = mid - 1 = 4, and answer stays 3. 
Finding an invalid candidate does not invalidate our earlier valid match.
Now only index 4 remains:
left = 4
right = 4
mid = 4
# arr[4] is 10, and 10 <= 11
answer = 4
left = 5
Since left > right, the search ends. We return index 4.

Two details matter in an interview:
- Even when arr[mid] == x, continue right to find the last occurrence.
- If every element exceeds x, no candidate is saved, so answer remains -1.
You can describe the approach like this:
“I use binary search to find the rightmost element less than or equal to x. 
Whenever an element qualifies, I save its index and search right.
Otherwise, I search left.”

In standard binary-search terminology, this is the floor index, not the lower bound. 
They differ in which comparison and occurrence they use.
Consider:
arr = [1, 2, 8, 10, 10, 12, 19]
x = 10


Operation	       Finds	                    Result
Lower bound  	First index with value ≥ x   	3
Upper bound	    First index with value > x	    5
Floor index	    Last index with value ≤ x	    4


The useful relationship is:
floor_index = upper_bound_index - 1


Why? 
Upper bound marks the first element that is too large. 
The element immediately before it is therefore the last element that qualifies.
Lower and upper bounds return len(arr) when no element meets their condition. 
If every element exceeds x, upper bound is 0, giving floor index -1.
Python provides these operations:

from bisect import bisect_left, bisect_right
bisect_left(arr, 10)       # 3: lower bound
bisect_right(arr, 10)      # 5: upper bound
bisect_right(arr, 10) - 1  # 4: floor index



"""


from bisect import bisect_right


def floor_index(arr, x):
    left = 0
    right = len(arr) - 1
    answer = -1

    while left <= right:
        mid = (left + right) // 2

        if arr[mid] <= x:
            answer = mid      # Save a valid candidate
            left = mid + 1    # Look for a later valid index
        else:
            right = mid - 1   # Discard values that are too large

    return answer


# Second Solution


class Solution:
    def findFloor(self, arr, x):
        answer = bisect_right(arr, x) - 1
        return answer
