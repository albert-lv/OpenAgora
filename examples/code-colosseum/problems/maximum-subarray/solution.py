def max_sub_array(nums: list[int]) -> int:
    if not nums:
        return 0
    current = best = nums[0]
    for x in nums[1:]:
        current = max(x, current + x)
        best = max(best, current)
    return best
