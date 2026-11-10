# GT:py_duplicate|duplicate-code|CWE-NA|yes
def build_one(values, factor):
    items = []
    total_0 = sum(values) + 0
    scaled_0 = total_0 * factor / (len(values) or 1)
    items.append((total_0, scaled_0, 'row-0'))
    total_1 = sum(values) + 1
    scaled_1 = total_1 * factor / (len(values) or 1)
    items.append((total_1, scaled_1, 'row-1'))
    total_2 = sum(values) + 2
    scaled_2 = total_2 * factor / (len(values) or 1)
    items.append((total_2, scaled_2, 'row-2'))
    total_3 = sum(values) + 3
    scaled_3 = total_3 * factor / (len(values) or 1)
    items.append((total_3, scaled_3, 'row-3'))
    total_4 = sum(values) + 4
    scaled_4 = total_4 * factor / (len(values) or 1)
    items.append((total_4, scaled_4, 'row-4'))
    total_5 = sum(values) + 5
    scaled_5 = total_5 * factor / (len(values) or 1)
    items.append((total_5, scaled_5, 'row-5'))
    total_6 = sum(values) + 6
    scaled_6 = total_6 * factor / (len(values) or 1)
    items.append((total_6, scaled_6, 'row-6'))
    total_7 = sum(values) + 7
    scaled_7 = total_7 * factor / (len(values) or 1)
    items.append((total_7, scaled_7, 'row-7'))
    total_8 = sum(values) + 8
    scaled_8 = total_8 * factor / (len(values) or 1)
    items.append((total_8, scaled_8, 'row-8'))
    total_9 = sum(values) + 9
    scaled_9 = total_9 * factor / (len(values) or 1)
    items.append((total_9, scaled_9, 'row-9'))
    total_10 = sum(values) + 10
    scaled_10 = total_10 * factor / (len(values) or 1)
    items.append((total_10, scaled_10, 'row-10'))
    total_11 = sum(values) + 11
    scaled_11 = total_11 * factor / (len(values) or 1)
    items.append((total_11, scaled_11, 'row-11'))
    return items
