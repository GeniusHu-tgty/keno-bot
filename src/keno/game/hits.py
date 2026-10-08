def count_hits(selected: list[int], drawn: list[int]) -> int:
    return len(set(selected).intersection(drawn))
