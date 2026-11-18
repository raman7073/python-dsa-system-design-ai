import math
import random


class IntroSelect:
    def __init__(self, nums):
        self.nums = nums
        self.first_index = 0
        self.last_index = len(nums) - 1

    def run(self, k):
        depth = 2 * max(1, int(math.log2(len(self.nums))))
        index = self.select(self.first_index, self.last_index, k - 1, depth)
        return self.nums[index]

    def select(self, first_index, last_index, k, depth):
        if depth > 0:
            pivot_index = random.randint(
                first_index, last_index)     # fast path
        else:
            pivot_index = self.median_of_medians(
                first_index, last_index)  # safe path

        pivot_index = self.partition(first_index, last_index, pivot_index)

        if pivot_index < k:
            return self.select(pivot_index + 1, last_index, k, depth - 1)

        elif pivot_index > k:
            return self.select(first_index, pivot_index - 1, k, depth - 1)

        return pivot_index

    def partition(self, first_index, last_index, pivot_index):
        self.swap(pivot_index, last_index)
        for i in range(first_index, last_index):
            if self.nums[i] < self.nums[last_index]:
                self.swap(i, first_index)
                first_index += 1
        self.swap(first_index, last_index)

        return first_index

    def median_of_medians(self, first_index, last_index):
        if last_index - first_index < 5:
            self.insertion_sort(first_index, last_index)
            return (first_index + last_index) // 2

        groups = 0
        for start in range(first_index, last_index + 1, 5):
            end = min(start + 4, last_index)
            self.insertion_sort(start, end)
            self.swap((start + end) // 2, first_index + groups)
            groups += 1

        mid = first_index + (groups - 1) // 2
        # depth 0, stays MoM
        return self.select(first_index, first_index + groups - 1, mid, 0)

    def insertion_sort(self, first_index, last_index):
        for i in range(first_index + 1, last_index + 1):
            j = i
            while j > first_index and self.nums[j - 1] > self.nums[j]:
                self.swap(j - 1, j)
                j -= 1

    def swap(self, i, j):
        self.nums[i], self.nums[j] = self.nums[j], self.nums[i]
