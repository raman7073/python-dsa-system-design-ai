"""
Question Link : https://www.geeksforgeeks.org/batch/cip-1/track/P100-Searching/problem/left-index-1587115620

Given a sorted array of positive integers (elements may be repeated) and a number x. 
The task is to find the leftmost index of x in the given array.

Example 1:

Input: arr[] = [1, 1, 2, 2, 3, 4, 5, 5, 6, 7], x = 1
Output: 0
Explanation: 1 is present two times in the array and its leftmost index is 0.
Input: arr[] = [10, 20, 20, 20, 20, 20, 20], x = 20
Output: 1
Explanation: 20 is present 5 time, but its leftmost index is 1.
"""


def leftmost_index(arr, x):
    left = 0
    right = len(arr) - 1
    answer = -1

    while left <= right:
        mid = (left + right) // 2

        if arr[mid] < x:
            left = mid + 1

        elif arr[mid] > x:
            right = mid - 1

        else:
            answer = mid      # Save a valid match
            right = mid - 1    # Look for an earlier match

    return answer


"""
Interview follow-up: Why do we use while left <= right instead of while left < right?

when left == right, one candidate still remains, and skipping it could miss the leftmost match.
A small distinction: neighbouring indexes such as 0 and 1 represent two elements.
Equal boundaries such as 0 and 0 represent one element.
Here’s an example where skipping that last element gives the wrong answer:
arr = [20, 20, 20]x = 20


First iteration:
left = 0right = 2mid = 1# Found 20:answer = 1right = 0


Now left == right == 0, and index 0 is the actual leftmost match.
Loop condition	What happens
left < right	Stops immediately; incorrectly returns 1
left <= right	Checks index 0; updates the answer to 0


In an interview, you can explain:
“Both boundaries are inclusive, so equal boundaries still contain one candidate. 
We stop only when left > right, meaning the search range is empty.”
"""
