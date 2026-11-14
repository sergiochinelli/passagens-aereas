from decimal import Decimal


def format_brl(value) -> str:
    """Formata valor monetario no padrao Real brasileiro: R$ 1.234.567,89."""
    if value is None:
        return "R$ -"
    number = Decimal(str(value)).quantize(Decimal("0.01"))
    integer, _, cents = f"{number:.2f}".partition(".")
    groups = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    return "R$ " + ".".join(reversed(groups)) + "," + cents
