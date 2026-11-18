class QuickSelect:
    def __init__(self, nums):
        self.nums = nums
        self.first_index = 0
        self.last_index = len(nums) - 1

    def run(self, k):
        return self.select(self.first_index, self.last_index, k - 1)

    def select(self, first_index, last_index, k):
        pivot_index = self.partition(first_index, last_index)

        if pivot_index < k:
            return self.select(pivot_index + 1, last_index, k)

        elif pivot_index > k:
            return self.select(first_index, pivot_index - 1, k)

        return self.nums[pivot_index]

    def partition(self, first_index, last_index):
        pivot_index = self.median_of_medians(
            first_index, last_index)   # was: random.randint(...)
        self.swap(pivot_index, last_index)
        for i in range(first_index, last_index):
            if self.nums[i] < self.nums[last_index]:
                self.swap(i, first_index)
                first_index += 1
        self.swap(first_index, last_index)

        return first_index

    def median_of_medians(self, first_index, last_index):
        # small range: sort it and take the middle
        if last_index - first_index < 5:
            self.insertion_sort(first_index, last_index)
            return (first_index + last_index) // 2

        # sort each group of 5 and move its median to the front
        groups = 0
        for start in range(first_index, last_index + 1, 5):
            end = min(start + 4, last_index)
            self.insertion_sort(start, end)
            self.swap((start + end) // 2, first_index + groups)
            groups += 1

        # use YOUR select to get the median VALUE of the medians
        mid = first_index + (groups - 1) // 2
        median_value = self.select(first_index, first_index + groups - 1, mid)

        # find where that value sits in the range
        for i in range(first_index, last_index + 1):
            if self.nums[i] == median_value:
                return i

    def insertion_sort(self, first_index, last_index):
        for i in range(first_index + 1, last_index + 1):
            j = i
            while j > first_index and self.nums[j - 1] > self.nums[j]:
                self.swap(j - 1, j)
                j -= 1

    def swap(self, i, j):
        self.nums[i], self.nums[j] = self.nums[j], self.nums[i]


x = [1, 2, -5, 4, 100, -7, 3, 10]
select = QuickSelect(x)
print(select.run(3))
