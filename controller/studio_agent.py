"""Strict JSON helper used by the supported controller transport."""
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field: '+key)
        result[key] = value
    return result

