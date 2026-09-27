"""Salesforce 15-character to 18-character Ids. See docs/salesforce.md."""


def to_18(id15: str) -> str:
    id15 = id15.strip()
    if len(id15) == 18:
        return id15
    if len(id15) != 15:
        raise ValueError("Salesforce id must be 15 or 18 chars")
    suffix = []
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    for block in range(3):
        flags = 0
        for bit in range(5):
            char = id15[block * 5 + bit]
            if "A" <= char <= "Z":
                flags |= 1 << bit
        suffix.append(alphabet[flags])
    return id15 + "".join(suffix)
