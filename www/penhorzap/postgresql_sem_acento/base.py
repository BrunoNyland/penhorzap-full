"""Backend PostgreSQL em que as buscas ignoram acento, como no MySQL.

O penhorzap rodou sobre MySQL com utf8mb4_unicode_ci, que compara sem acento
e sem maiúscula: "joao" achava "JOÃO" na busca de clientes do painel. O
PostgreSQL já ignora maiúscula nos lookups `i*` (UPPER dos dois lados), mas
não acento. Aqui os dois lados passam também por UNACCENT — extensão criada
na migration core/0035 —, e as buscas da API continuam como eram, sem trocar
nenhuma chamada.

Só os lookups `i*` mudam. O `exact` continua exato: mexer no `=` mudaria a
semântica de chaves (cpf, wa_message_id) e tiraria o uso dos índices.
"""

from django.db.backends.postgresql import base, operations

INSENSIVEIS = ("iexact", "icontains", "istartswith", "iendswith")


class DatabaseOperations(operations.DatabaseOperations):
    def lookup_cast(self, lookup_type, internal_type=None):
        cast = super().lookup_cast(lookup_type, internal_type)
        if lookup_type in INSENSIVEIS:
            # O Django devolve "UPPER(<coluna>::text)".
            coluna = cast.removeprefix("UPPER(").removesuffix(")")
            return f"UPPER(UNACCENT({coluna}))"
        return cast


def _sem_acento(regras, de, para):
    return {**regras, **{k: v.replace(de, para) for k, v in regras.items() if k in INSENSIVEIS}}


class DatabaseWrapper(base.DatabaseWrapper):
    ops_class = DatabaseOperations
    # Lado do valor buscado: literal (operators) ou expressão, como F() (pattern_ops).
    operators = _sem_acento(base.DatabaseWrapper.operators, "UPPER(%s)", "UPPER(UNACCENT(%s))")
    pattern_ops = _sem_acento(
        base.DatabaseWrapper.pattern_ops, "UPPER({})", "UPPER(UNACCENT({}))"
    )
