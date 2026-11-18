def tail_head(n):
    if n == 0:
        print(n)
        return
    print(n)
    tail_head(n-1)
    print(n)
    # tail_head(n-1)


tail_head(5)
